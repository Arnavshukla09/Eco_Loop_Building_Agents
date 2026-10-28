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
    """Verify health endpoint returns status, liveness, readiness, and model info."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("ok", "degraded", "starting")
        assert "liveness" in data
        assert "readiness" in data
        assert "controller_mode" in data
        assert "model" in data


@pytest.mark.asyncio
async def test_api_key_auth_protection():
    """Verify mutating endpoints are guarded when API_KEY is configured."""
    original_key = settings.API_KEY
    try:
        settings.API_KEY = "test-secret-guard"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            # 1. Without header -> 403 Forbidden
            resp = await client.post(
                "/api/setpoint",
                json={"zone": "Core", "cooling": 24.0, "heating": 20.0},
            )
            assert resp.status_code == 403

            # 2. With wrong key -> 403 Forbidden
            resp = await client.post(
                "/api/setpoint",
                json={"zone": "Core", "cooling": 24.0, "heating": 20.0},
                headers={"Authorization": "Bearer wrong-key"},
            )
            assert resp.status_code == 403

            # 3. Read endpoints remain public
            resp_health = await client.get("/api/health")
            assert resp_health.status_code == 200
    finally:
        settings.API_KEY = original_key


@pytest.mark.asyncio
async def test_production_fail_closed_security():
    """Verify in production mode with unset API_KEY, mutating endpoints fail closed (500)."""
    orig_env = settings.ENVIRONMENT
    orig_key = settings.API_KEY
    try:
        settings.ENVIRONMENT = "production"
        settings.API_KEY = None
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/setpoint",
                json={"zone": "Core", "cooling": 24.0, "heating": 20.0},
            )
            assert resp.status_code == 500  # Fail-closed misconfiguration error
    finally:
        settings.ENVIRONMENT = orig_env
        settings.API_KEY = orig_key


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
async def test_websocket_message_payload_format():
    """Verify state store produces valid DashboardUpdate matching frontend type expectation."""
    update = state_store.get_dashboard_update()
    assert update is not None
    data = update.model_dump(mode="json")
    # Verify exact contract required by frontend useWebSocket hook
    assert data["type"] == "state_update"
    assert "building" in data
    assert "zones" in data["building"]
    assert "metrics" in data
    assert "energy_savings_pct" in data["metrics"]
    assert "comfort_score" in data["metrics"]


@pytest.mark.asyncio
async def test_simulation_reset_endpoint_and_auth():
    """Verify /api/simulation/reset endpoint exists, executes under lock, and respects auth."""
    from backend.controller import controller
    from backend.energyplus_runner import SimulatedBuildingEnvironment

    if controller.env is None:
        controller.env = SimulatedBuildingEnvironment(seed=42)
        controller.baseline_env = SimulatedBuildingEnvironment(is_baseline=True, seed=42)

    original_key = settings.API_KEY
    try:
        # In open mode, reset returns 200 and initial state
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/simulation/reset")
            assert resp.status_code == 200
            res = resp.json()
            assert res["success"] is True
            assert res["timestep"] == 1

        # With API key configured, unauthenticated reset returns 403
        settings.API_KEY = "lock-secret"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp_fail = await client.post("/api/simulation/reset")
            assert resp_fail.status_code == 403

            resp_ok = await client.post(
                "/api/simulation/reset",
                headers={"Authorization": "Bearer lock-secret"},
            )
            assert resp_ok.status_code == 200
    finally:
        settings.API_KEY = original_key


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


@pytest.mark.asyncio
async def test_all_mutating_endpoints_auth_matrix():
    """Verify all mutating REST endpoints enforce auth when API_KEY is set."""
    original_key = settings.API_KEY
    try:
        settings.API_KEY = "vault-token-xyz"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            endpoints = [
                ("POST", "/api/setpoint", {"zone": "Core", "cooling": 24.0, "heating": 20.0}),
                ("POST", "/api/simulation/speed?speedup=10.0", None),
                ("POST", "/api/simulation/reset", None),
            ]
            for method, url, body in endpoints:
                # 1. Missing auth header -> 403
                res_missing = await client.request(method, url, json=body)
                assert res_missing.status_code == 403, f"{url} accepted missing auth header"

                # 2. Invalid auth header -> 403
                res_invalid = await client.request(
                    method, url, json=body, headers={"Authorization": "Bearer wrong-token"}
                )
                assert res_invalid.status_code == 403, f"{url} accepted invalid token"

                # 3. Valid auth header -> 200
                res_valid = await client.request(
                    method, url, json=body, headers={"Authorization": "Bearer vault-token-xyz"}
                )
                assert res_valid.status_code == 200, f"{url} rejected valid token: {res_valid.text}"
    finally:
        settings.API_KEY = original_key


@pytest.mark.asyncio
async def test_mcp_mutating_tools_auth_protection():
    """Verify mutating MCP tools require valid api_key parameter when auth is active."""
    from backend.controller import controller
    from backend.energyplus_runner import SimulatedBuildingEnvironment
    if controller.env is None:
        controller.env = SimulatedBuildingEnvironment(seed=42)

    original_key = settings.API_KEY
    original_env = settings.ENVIRONMENT
    try:
        settings.API_KEY = "mcp-secret-key"
        # 1. Without api_key -> fails with Forbidden
        res1 = await update_setpoint("Core", 24.0, 20.0)
        assert res1["success"] is False
        assert "Forbidden" in res1["error"]

        res2 = await update_all_setpoints(24.0, 20.0)
        assert res2["success"] is False
        assert "Forbidden" in res2["error"]

        res3 = await run_simulation_step()
        assert res3["success"] is False
        assert "Forbidden" in res3["error"]

        # 2. With wrong api_key -> fails
        res_bad = await update_setpoint("Core", 24.0, 20.0, api_key="bad-key")
        assert res_bad["success"] is False
        assert "Forbidden" in res_bad["error"]

        # 3. With correct api_key -> succeeds
        res_good = await update_setpoint("Core", 24.0, 20.0, api_key="mcp-secret-key")
        assert res_good["success"] is True

        res_step = await run_simulation_step(api_key="mcp-secret-key")
        assert res_step["success"] is True

        # 4. Fail-closed check: production with unset API_KEY
        settings.ENVIRONMENT = "production"
        settings.API_KEY = None
        res_prod = await update_setpoint("Core", 24.0, 20.0)
        assert res_prod["success"] is False
        assert "misconfiguration" in res_prod["error"].lower()

    finally:
        settings.API_KEY = original_key
        settings.ENVIRONMENT = original_env


@pytest.mark.asyncio
async def test_canonical_setpoint_validation():
    """Verify strict validation and rejection of out-of-range setpoints across REST and MCP."""
    from backend.controller import controller
    from backend.energyplus_runner import SimulatedBuildingEnvironment
    if controller.env is None:
        controller.env = SimulatedBuildingEnvironment(seed=42)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Case A: Deadband violation (< 1.5°C gap)
        resp = await client.post("/api/setpoint", json={"zone": "Core", "cooling": 21.0, "heating": 20.0})
        assert resp.status_code == 422
        mcp_res = await update_setpoint("Core", 21.0, 20.0)
        assert mcp_res["success"] is False
        assert "Deadband" in mcp_res["error"]

        # Case B: Cooling setpoint exceeds max (30.0°C)
        resp = await client.post("/api/setpoint", json={"zone": "Core", "cooling": 32.0, "heating": 20.0})
        assert resp.status_code == 422
        mcp_res = await update_setpoint("Core", 32.0, 20.0)
        assert mcp_res["success"] is False
        assert "outside valid range" in mcp_res["error"]

        # Case C: Heating setpoint below min (16.0°C)
        resp = await client.post("/api/setpoint", json={"zone": "Core", "cooling": 24.0, "heating": 14.0})
        assert resp.status_code == 422
        mcp_res = await update_setpoint("Core", 24.0, 14.0)
        assert mcp_res["success"] is False
        assert "outside valid range" in mcp_res["error"]

        # Case D: Unknown zone
        resp = await client.post("/api/setpoint", json={"zone": "Roof", "cooling": 24.0, "heating": 20.0})
        assert resp.status_code == 422
        mcp_res = await update_setpoint("Roof", 24.0, 20.0)
        assert mcp_res["success"] is False
        assert "Unknown zone" in mcp_res["error"]


def test_websocket_real_connection_and_payload():
    """Test full WebSocket connection lifecycle using Starlette TestClient."""
    from starlette.testclient import TestClient
    import json

    client = TestClient(app)
    with client.websocket_connect("/ws") as websocket:
        # 1. Verify initial message on connect
        data = websocket.receive_text()
        parsed = json.loads(data)
        assert parsed.get("type") == "state_update"
        assert "building" in parsed
        assert "metrics" in parsed
        assert "zones" in parsed["building"]

        # 2. Ping-pong keepalive test
        websocket.send_text("ping")
        pong = websocket.receive_text()
        assert pong == "pong"
