import pytest
import httpx
from datetime import datetime, timezone
from backend.app import app
from backend.models import BuildingObservation, ZoneState, SetpointCommand
from backend.state import state_store
from backend.mcp_server import (
    read_building_state,
    get_hvac_setpoints,
    update_setpoint,
    update_all_setpoints,
    run_simulation_step,
    get_energy_usage,
    calculate_savings,
    get_comfort_report,
    get_outdoor_conditions,
    get_ai_decision,
)
from config.settings import settings


@pytest.fixture(autouse=True)
def setup_state():
    zones = {
        z: ZoneState(
            zone_id=z,
            temperature=22.0,
            setpoint_cooling=24.0,
            setpoint_heating=20.0,
            pmv_score=0.1,
            ppd_score=5.0,
            humidity=50.0,
        )
        for z in settings.ZONES
    }
    obs = BuildingObservation(
        timestamp=datetime.now(timezone.utc),
        simulation_time=datetime(2024, 1, 15, 12, 0),
        zones=zones,
        outdoor_temp=10.0,
        outdoor_humidity=60.0,
        total_energy_kwh=50.0,
        hvac_power_kw=8.0,
        occupancy=0.6,
        timestep=5,
    )
    state_store.update_observation(obs)


@pytest.mark.asyncio
async def test_api_health_endpoint():
    """Verify health endpoint returns status, simulation, and model info."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "model" in data


@pytest.mark.asyncio
async def test_api_mcp_tools_listing():
    """Verify MCP tools list returns exactly 10 registered tools."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/mcp/tools")
        assert resp.status_code == 200
        data = resp.json()
        tools = data["tools"]
        assert len(tools) == 10
        tool_names = [t["name"] for t in tools]
        assert "run_simulation_step" in tool_names
        assert "read_building_state" in tool_names
        assert "update_setpoint" in tool_names


@pytest.mark.asyncio
async def test_setpoint_validation_endpoint():
    """Verify manual setpoint endpoint enforces cooling > heating validation."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Invalid: cooling below heating (e.g. cooling=19.0, heating=22.0)
        resp = await client.post(
            "/api/setpoint",
            json={"zone": "Core", "cooling": 19.0, "heating": 22.0},
        )
        assert resp.status_code == 422  # Pydantic validation error


@pytest.mark.asyncio
async def test_speed_validation_endpoint():
    """Verify speed endpoint rejects out of bound speed values."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/simulation/speed?speedup=0.5")
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_mcp_direct_tools():
    """Verify direct invocation of MCP tool functions."""
    state = read_building_state()
    assert "zones" in state
    assert state["outdoor_temp_c"] == 10.0

    setpoints = get_hvac_setpoints()
    assert "Core" in setpoints

    energy = get_energy_usage()
    assert energy["total_energy_kwh"] == 50.0

    comfort = get_comfort_report()
    assert "building_avg_pmv" in comfort

    conditions = get_outdoor_conditions()
    assert conditions["season"] == "winter"
