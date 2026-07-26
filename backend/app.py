"""
backend/app.py
───────────────
FastAPI application — the main entry point for the backend.

Endpoints
─────────
GET  /                     → Serves the React dashboard (index.html)
GET  /api/status           → Full current building state (JSON)
GET  /api/history          → Historical data for chart initialisation
GET  /api/health           → System health check
POST /api/setpoint         → Manual setpoint override
POST /api/simulation/speed → Adjust simulation speed factor
WS   /ws                   → Real-time WebSocket stream for dashboard

Mounts
──────
/mcp/  → FastMCP SSE server (MCP tools accessible at /mcp/sse)
/static → React build output
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.controller import controller
from backend.dashboard_api import broadcast_loop, websocket_endpoint
from backend.mcp_server import mcp
from backend.models import HealthStatus, SetpointCommand
from backend.state import state_store
from config.settings import settings

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── FastAPI application ───────────────────────────────────────────────────────
app = FastAPI(
    title="Honeywell Eco-Loop Building Agent",
    description=(
        "Autonomous AI system controlling an EnergyPlus building simulation "
        "via an open-source LLM and MCP server."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Mount MCP server ──────────────────────────────────────────────────────────
# FastMCP 3.x uses http_app(); FastMCP 2.x used sse_app().
# Mounted at /mcp — tools accessible at /mcp/sse or /mcp/
try:
    if hasattr(mcp, "http_app"):
        app.mount("/mcp", mcp.http_app())
        logger.info("FastMCP 3.x server mounted at /mcp (HTTP)")
    elif hasattr(mcp, "sse_app"):
        app.mount("/mcp", mcp.sse_app())
        logger.info("FastMCP 2.x server mounted at /mcp/sse")
    else:
        logger.warning("FastMCP mount method not found. MCP tools available via shared state.")
except Exception as exc:
    logger.warning("Could not mount MCP app: %s. MCP tools still available via state.", exc)

# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────
_broadcast_task: asyncio.Task | None = None
_app_start_time = time.monotonic()


@app.on_event("startup")
async def startup_event() -> None:
    global _broadcast_task
    logger.info("=" * 60)
    logger.info("  Honeywell Eco-Loop Building Agent  v1.0.0")
    logger.info("  Dashboard  → http://localhost:%d", settings.API_PORT)
    logger.info("  API docs   → http://localhost:%d/docs", settings.API_PORT)
    logger.info("  MCP tools  → http://localhost:%d/mcp/sse", settings.API_PORT)
    logger.info("=" * 60)

    # Start the autonomous controller (simulation + AI agent)
    await controller.start()

    # Start WebSocket broadcast loop
    _broadcast_task = asyncio.create_task(broadcast_loop(), name="ws-broadcast")

    state_store.set_mcp_running(True)
    logger.info("All systems running.")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    global _broadcast_task
    if _broadcast_task and not _broadcast_task.done():
        _broadcast_task.cancel()
    await controller.stop()
    logger.info("Eco-Loop shut down cleanly.")


# ── WebSocket endpoint ────────────────────────────────────────────────────────
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await websocket_endpoint(ws)


# ── REST API endpoints ────────────────────────────────────────────────────────

@app.get("/api/status")
async def get_status() -> JSONResponse:
    """Return the full current building state as JSON."""
    update = state_store.get_dashboard_update()
    if update is None:
        raise HTTPException(status_code=503, detail="Simulation not started yet.")
    return JSONResponse(content=update.model_dump(mode="json"))


@app.get("/api/history")
async def get_history(limit: int = 100) -> JSONResponse:
    """Return the last `limit` historical data points for chart initialisation."""
    limit  = max(1, min(limit, settings.HISTORY_MAX_LEN))
    entries = state_store.get_history(limit=limit)
    return JSONResponse(content={"entries": [e.model_dump(mode="json") for e in entries]})


@app.get("/api/health")
async def health_check() -> HealthStatus:
    """System health endpoint."""
    obs = state_store.get_observation()
    return HealthStatus(
        status="ok",
        simulation_running=state_store.is_simulation_running(),
        llm_available=state_store.is_llm_available(),
        mcp_running=state_store.is_mcp_running(),
        uptime_seconds=round(time.monotonic() - _app_start_time, 1),
        simulation_mode=settings.SIMULATION_MODE,
        model=settings.LLM_MODEL,
        timestep=obs.timestep if obs else 0,
    )


@app.post("/api/setpoint")
async def manual_setpoint(cmd: SetpointCommand) -> JSONResponse:
    """Manual setpoint override.  Bypasses AI for immediate effect."""
    if cmd.zone is not None:
        if cmd.zone not in settings.ZONES:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown zone '{cmd.zone}'. Valid: {settings.ZONES}",
            )
        ok = await controller.env.set_setpoint(cmd.zone, cmd.cooling, cmd.heating)
        message = f"Setpoint applied to {cmd.zone}." if ok else "Failed to apply setpoint."
    else:
        await controller.env.set_all_setpoints(cmd.cooling, cmd.heating)
        ok = True
        message = "Setpoints applied to all zones."

    return JSONResponse(
        content={
            "success": ok,
            "zone": cmd.zone or "ALL",
            "cooling_c": cmd.cooling,
            "heating_c": cmd.heating,
            "message": message,
        }
    )


@app.post("/api/simulation/speed")
async def set_speed(speedup: float) -> JSONResponse:
    """Adjust simulation speedup factor (1 = real time, 60 = 1 simulated hour per second)."""
    speedup = max(1.0, min(3600.0, speedup))
    settings.SPEEDUP_FACTOR = speedup
    return JSONResponse(content={"speedup_factor": speedup})


@app.get("/api/mcp/tools")
async def list_mcp_tools() -> JSONResponse:
    """List all available MCP tools with their descriptions."""
    tools = [
        {
            "name": "read_building_state",
            "description": "Get the full current state of all zones.",
        },
        {
            "name": "get_hvac_setpoints",
            "description": "Get current heating/cooling setpoints per zone.",
        },
        {
            "name": "update_setpoint",
            "description": "Update setpoints for a specific zone.",
        },
        {
            "name": "update_all_setpoints",
            "description": "Apply same setpoints to all zones.",
        },
        {
            "name": "get_energy_usage",
            "description": "Energy consumption metrics.",
        },
        {
            "name": "calculate_savings",
            "description": "Energy savings vs baseline.",
        },
        {
            "name": "get_comfort_report",
            "description": "PMV/PPD comfort analysis per zone.",
        },
        {
            "name": "get_outdoor_conditions",
            "description": "Outdoor temperature, humidity, and time context.",
        },
        {
            "name": "get_ai_decision",
            "description": "Last AI agent decision and reasoning.",
        },
    ]
    return JSONResponse(content={"tools": tools, "mcp_endpoint": "/mcp/sse"})


# ── Serve React frontend ──────────────────────────────────────────────────────
_FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"
_FRONTEND_DEV  = Path(__file__).parent.parent / "frontend" / "index.html"


def _setup_static() -> None:
    """Mount the built frontend if it exists."""
    if _FRONTEND_DIST.exists():
        app.mount(
            "/assets",
            StaticFiles(directory=str(_FRONTEND_DIST / "assets")),
            name="assets",
        )
        logger.info("Serving built React frontend from %s.", _FRONTEND_DIST)
    else:
        logger.warning(
            "Frontend build not found at %s. "
            "Run 'npm run build' inside frontend/ or use 'npm run dev' on port 5173.",
            _FRONTEND_DIST,
        )


_setup_static()


@app.get("/", include_in_schema=False)
@app.get("/{full_path:path}", include_in_schema=False)
async def serve_frontend(full_path: str = "") -> FileResponse:
    """Serve the React SPA for any non-API route."""
    # Don't intercept API, docs, MCP, or WebSocket routes
    for prefix in ("/api/", "/docs", "/redoc", "/ws", "/mcp/", "/assets/"):
        if full_path.startswith(prefix.lstrip("/")):
            raise HTTPException(status_code=404)

    if _FRONTEND_DIST.exists():
        index = _FRONTEND_DIST / "index.html"
    elif _FRONTEND_DEV.exists():
        index = _FRONTEND_DEV
    else:
        return JSONResponse(
            content={
                "message": "Eco-Loop API running!",
                "dashboard": "Build the React frontend: cd frontend && npm run build",
                "api_docs": f"http://localhost:{settings.API_PORT}/docs",
            }
        )
    return FileResponse(str(index))
