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
from contextlib import asynccontextmanager
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

# ── FastMCP ASGI application ──────────────────────────────────────────────────
# In FastMCP 3.x, http_app(path="/") serves the MCP endpoint directly at root of mount
mcp_asgi_app = mcp.http_app(path="/")

# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────
_broadcast_task: asyncio.Task | None = None
_app_start_time = time.monotonic()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _broadcast_task
    logger.info("=" * 60)
    logger.info("  Honeywell Eco-Loop Building Agent  v1.0.0")
    logger.info("  Dashboard  → http://localhost:%d", settings.API_PORT)
    logger.info("  API docs   → http://localhost:%d/docs", settings.API_PORT)
    logger.info("  MCP tools  → http://localhost:%d/mcp/", settings.API_PORT)
    logger.info("=" * 60)

    # FastMCP lifespan provides taskgroup execution for MCP clients
    async with mcp_asgi_app.lifespan(app):
        # Start the autonomous controller (simulation + AI agent)
        await controller.start()

        # Start WebSocket broadcast loop
        _broadcast_task = asyncio.create_task(broadcast_loop(), name="ws-broadcast")

        state_store.set_mcp_running(True)
        logger.info("All systems running.")

        try:
            yield
        finally:
            if _broadcast_task and not _broadcast_task.done():
                _broadcast_task.cancel()
                try:
                    await _broadcast_task
                except asyncio.CancelledError:
                    pass
            await controller.stop()
            state_store.set_mcp_running(False)
            logger.info("Eco-Loop shut down cleanly.")


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
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
# Browser CORS spec: cannot use allow_credentials=True with allow_origins=["*"]
allow_creds = False if "*" in settings.CORS_ORIGINS else True
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=allow_creds,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount MCP ASGI sub-application at /mcp
app.mount("/mcp", mcp_asgi_app)


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
    """Manual setpoint override. Validates safety constraints and applies setpoints."""
    if controller is None or controller.env is None:
        raise HTTPException(status_code=503, detail="Simulation environment not initialised.")

    # Clamp setpoints to allowable ranges and enforce minimum deadband
    cooling_c = max(settings.COOLING_SETPOINT_MIN, min(settings.COOLING_SETPOINT_MAX, cmd.cooling))
    heating_c = max(settings.HEATING_SETPOINT_MIN, min(settings.HEATING_SETPOINT_MAX, cmd.heating))
    if cooling_c < heating_c + 1.5:
        cooling_c = heating_c + 2.0

    if cmd.zone is not None:
        if cmd.zone not in settings.ZONES:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown zone '{cmd.zone}'. Valid: {settings.ZONES}",
            )
        ok = await controller.env.set_setpoint(cmd.zone, cooling_c, heating_c)
        message = f"Setpoint applied to {cmd.zone}." if ok else "Failed to apply setpoint."
        zone_applied = cmd.zone
    else:
        await controller.env.set_all_setpoints(cooling_c, heating_c)
        ok = True
        message = "Setpoints applied to all zones."
        zone_applied = "ALL"

    return JSONResponse(
        content={
            "success": ok,
            "zone": zone_applied,
            "cooling_c": round(cooling_c, 1),
            "heating_c": round(heating_c, 1),
            "message": message,
        }
    )


@app.post("/api/simulation/speed")
async def set_speed(speedup: float) -> JSONResponse:
    """
    Adjust simulation speedup factor (demo/local control).
    1.0 = real time, 60.0 = 1 simulated minute per second, max 3600.0.
    """
    if speedup < 1.0 or speedup > 3600.0:
        raise HTTPException(
            status_code=422,
            detail="Speedup factor must be between 1.0 and 3600.0.",
        )
    settings.SPEEDUP_FACTOR = speedup
    return JSONResponse(content={"speedup_factor": speedup, "message": "Simulation speed updated."})


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
            "name": "run_simulation_step",
            "description": "Advance the building simulation environment by one timestep.",
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
    return JSONResponse(content={"tools": tools, "mcp_endpoint": "/mcp/"})


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
