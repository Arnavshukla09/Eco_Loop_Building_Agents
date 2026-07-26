"""
backend/dashboard_api.py
────────────────────────
WebSocket connection manager.

Maintains a set of active browser connections and broadcasts
JSON state updates to all of them at a configurable interval.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Set

from fastapi import WebSocket, WebSocketDisconnect

from backend.state import state_store
from config.settings import settings

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages a pool of active WebSocket connections."""

    def __init__(self) -> None:
        self._active: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._active.add(ws)
        logger.info("Dashboard client connected.  Total: %d", len(self._active))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._active.discard(ws)
        logger.info("Dashboard client disconnected.  Total: %d", len(self._active))

    async def broadcast(self, payload: dict) -> None:
        """Send JSON payload to every connected client, dropping dead connections."""
        if not self._active:
            return
        message = json.dumps(payload, default=str)
        dead: Set[WebSocket] = set()
        async with self._lock:
            targets = set(self._active)
        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        if dead:
            async with self._lock:
                self._active -= dead
            logger.debug("Dropped %d stale WebSocket connection(s).", len(dead))

    @property
    def connection_count(self) -> int:
        return len(self._active)


# ── Singleton ─────────────────────────────────────────────────────────────────
manager = ConnectionManager()


# ── Background broadcast task ─────────────────────────────────────────────────
async def broadcast_loop() -> None:
    """
    Runs as a FastAPI background task.
    Broadcasts the current building state to all dashboard clients every
    WS_BROADCAST_INTERVAL seconds (or whenever state changes).
    """
    logger.info(
        "WebSocket broadcast loop started (interval %.1fs).",
        settings.WS_BROADCAST_INTERVAL,
    )
    while True:
        try:
            # Wait for a state update OR the max broadcast interval
            await state_store.wait_for_update(timeout=settings.WS_BROADCAST_INTERVAL)
            update = state_store.get_dashboard_update()
            if update is not None and manager.connection_count > 0:
                await manager.broadcast(update.model_dump())
        except asyncio.CancelledError:
            logger.info("Broadcast loop cancelled.")
            break
        except Exception as exc:
            logger.exception("Error in broadcast loop: %s", exc)
            await asyncio.sleep(1.0)


# ── WebSocket endpoint handler (called from app.py) ───────────────────────────
async def websocket_endpoint(ws: WebSocket) -> None:
    """
    Accept a WebSocket connection, send the current state immediately,
    then keep the connection alive until the client disconnects.
    """
    await manager.connect(ws)
    try:
        # Send current state immediately on connect
        update = state_store.get_dashboard_update()
        if update:
            await ws.send_text(json.dumps(update.model_dump(), default=str))

        # Keep connection alive; client sends ping, we echo pong
        while True:
            try:
                data = await asyncio.wait_for(ws.receive_text(), timeout=30.0)
                if data == "ping":
                    await ws.send_text("pong")
            except asyncio.TimeoutError:
                # Send a keepalive so the browser doesn't drop the connection
                await ws.send_text(json.dumps({"type": "keepalive"}, default=str))
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("WebSocket error: %s", exc)
    finally:
        await manager.disconnect(ws)
