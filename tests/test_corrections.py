"""Regressions for baseline parity, truthful actuation, and service lifecycle."""
import asyncio
import threading
from datetime import timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy import text

from backend.app import app, MCPAuthMiddleware
from backend.controller import AutonomousController, controller
from backend.database import close_db, get_engine, init_db
from backend.energyplus_runner import EnergyPlusBuildingEnvironment, SimulatedBuildingEnvironment
from backend.llm_agent import BuildingAIAgent, _rule_based_decision
from backend.mcp_server import update_setpoint, _verify_mcp_auth
from backend.models import SetpointCommand, validate_setpoints
from backend.providers import OllamaProvider
from backend.repository import repository
from backend.state import BuildingStateStore, state_store
from config.settings import settings


@pytest.mark.asyncio
async def test_live_baseline_matches_inputs_through_reset():
    ctrl = AutonomousController()
    await ctrl._initialise_environment()
    for _ in range(8):
        obs = await ctrl.step_simulation()
        reference = ctrl.baseline_env
        assert ctrl.env.seed == reference.seed
        assert ctrl.env._weather._rng.getstate() == reference._weather._rng.getstate()
        assert ctrl.env._rng.getstate() == reference._rng.getstate()
        assert state_store.get_metrics().baseline_power_kw is not None
    await ctrl.reset_simulation()
    assert ctrl.env.seed == ctrl.baseline_env.seed
    assert ctrl._step_count == state_store.get_observation().timestep == 1
    assert len(state_store.get_history()) == 1


@pytest.mark.asyncio
async def test_rest_and_mcp_report_clamped_values():
    controller.env = SimulatedBuildingEnvironment(seed=42)
    await controller.step_simulation()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/setpoint", json={"zone": "Core", "cooling": 30, "heating": 16})
    data = response.json()
    assert data["success"]
    assert (data["cooling_c"], data["heating_c"]) == (26, 18)
    assert data["requested"] == {"cooling": 30, "heating": 16}
    result = await update_setpoint("Core", 30, 16)
    assert result["applied_setpoints"]["Core"] == {"cooling": 28, "heating": 16}


@pytest.mark.asyncio
async def test_failed_zone_is_not_reported_as_applied():
    ctrl = AutonomousController()
    ctrl.env = SimulatedBuildingEnvironment(seed=42)
    await ctrl.step_simulation()
    original = ctrl.env.set_setpoint
    async def reject_one(zone, cooling, heating):
        return False if zone == "Core" else await original(zone, cooling, heating)
    with patch.object(ctrl.env, "set_setpoint", side_effect=reject_one):
        assert await ctrl.set_all_zone_setpoints(25, 19) is False
        assert state_store.get_observation().zones["Core"].setpoint_cooling == 24
        assert state_store.get_observation().zones["Perimeter_N"].setpoint_cooling == 25


@pytest.mark.asyncio
async def test_slew_limit_uses_state_after_lock_acquisition():
    ctrl = AutonomousController()
    ctrl.env = SimulatedBuildingEnvironment(seed=42)
    await ctrl.step_simulation()
    await ctrl.step_lock.acquire()
    pending = asyncio.create_task(ctrl.set_zone_setpoint("Core", 30, 16))
    await asyncio.sleep(0)
    state_store.update_setpoint("Core", 28, 18)
    ctrl.step_lock.release()
    assert await pending
    assert ctrl.env._sp_cool["Core"] == 30


@pytest.mark.asyncio
async def test_reset_discards_inflight_decision():
    ctrl = AutonomousController()
    ctrl.env = SimulatedBuildingEnvironment(seed=42)
    obs = await ctrl.step_simulation()
    decision = _rule_based_decision(obs)
    generation = ctrl._generation
    await ctrl.reset_simulation()
    assert await ctrl._apply_decision(decision, generation) is False
    assert state_store.get_decision() is None


@pytest.mark.asyncio
async def test_provider_exception_keeps_control_active():
    provider = MagicMock()
    provider.decide = AsyncMock(side_effect=RuntimeError("provider offline"))
    ctrl = AutonomousController(provider=provider)
    ctrl.env = SimulatedBuildingEnvironment(seed=42)
    await ctrl.step_simulation()
    ctrl._running = True
    completed = asyncio.Event()
    async def apply(decision, generation):
        assert decision.controller_source == "fallback"
        ctrl._running = False
        completed.set()
        return True
    with patch.object(ctrl, "_apply_decision", side_effect=apply):
        task = asyncio.create_task(ctrl._agent_loop())
        await asyncio.wait_for(completed.wait(), timeout=2)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_failed_reference_is_not_reused_out_of_sync():
    ctrl = AutonomousController()
    await ctrl._initialise_environment()
    with patch.object(ctrl.baseline_env, "step", AsyncMock(side_effect=RuntimeError("step lost"))):
        await ctrl.step_simulation()
    assert ctrl.baseline_env is None
    assert state_store.get_metrics().baseline_mode == "unmeasured"


@pytest.mark.asyncio
async def test_applied_decision_values_are_audited():
    from backend.database import get_db_session
    from backend.db_models import DecisionRecordModel
    from sqlalchemy import select
    import json
    await init_db()
    ctrl = AutonomousController()
    ctrl.env = SimulatedBuildingEnvironment(seed=42)
    obs = await ctrl.step_simulation()
    ctrl._current_run_id = await repository.create_run()
    decision = _rule_based_decision(obs)
    decision.zone_setpoints["Core"].cooling = 30
    decision.zone_setpoints["Core"].heating = 16
    await ctrl._apply_decision(decision)
    await asyncio.gather(*tuple(ctrl._persistence_tasks))
    async with get_db_session() as session:
        record = (await session.execute(select(DecisionRecordModel))).scalar_one()
    assert json.loads(record.zone_setpoints_json)["Core"] == {"cooling": 26, "heating": 18}


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_setpoints_are_rejected(bad):
    with pytest.raises(ValueError):
        validate_setpoints(bad, 20)
    with pytest.raises(ValueError):
        SetpointCommand(cooling=24, heating=bad)


@pytest.mark.asyncio
async def test_nonfinite_speed_is_rejected():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/simulation/speed?speedup=nan")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_history_excludes_archived_runs_and_prefers_memory():
    await init_db()
    controller.env = SimulatedBuildingEnvironment(seed=42)
    await controller.step_simulation()
    entry = state_store.get_history(1)[0]
    entry.sim_time = entry.sim_time.replace(tzinfo=timezone.utc)
    old_run = await repository.create_run()
    await repository.record_reading(old_run, entry, 1)
    active_run = await repository.create_run()
    state_store.reset()
    controller._current_run_id = active_run
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/history")).json()["entries"] == []
        await repository.record_reading(active_run, entry, 1)
        state_store._history.append(entry.model_copy(update={"avg_temp": 27.0}))
        entries = (await client.get("/api/history")).json()["entries"]
    assert len(entries) == 1 and entries[0]["avg_temp"] == 27.0


@pytest.mark.asyncio
async def test_baseline_power_survives_database_roundtrip():
    await init_db()
    ctrl = AutonomousController()
    await ctrl._initialise_environment()
    await ctrl.step_simulation()
    entry = state_store.get_history(1)[0]
    run = await repository.create_run()
    await repository.record_reading(run, entry, 1)
    assert (await repository.get_history(run))[0].baseline_power_kw == entry.baseline_power_kw


def test_zero_energy_reference_is_still_measured():
    store = BuildingStateStore()
    store.update_baseline_energy(0.0, 0.0)
    assert store._baseline_measured
    store.clear_baseline()
    assert not store._baseline_measured


@pytest.mark.asyncio
async def test_model_health_does_not_accept_different_size():
    fake = MagicMock()
    fake.list = AsyncMock(return_value=SimpleNamespace(models=[SimpleNamespace(model="qwen2.5:7b")]))
    provider = OllamaProvider("http://unused", "qwen2.5:1.5b")
    agent = BuildingAIAgent()
    agent._model = "qwen2.5:1.5b"
    with patch("ollama.AsyncClient", return_value=fake):
        assert not await provider.check_availability(force=True)
        assert not await agent.check_availability(force=True)


@pytest.mark.asyncio
async def test_mcp_query_key_requires_exact_parameter(monkeypatch):
    monkeypatch.setattr(settings, "API_KEY", "secret")
    called = []
    async def downstream(scope, receive, send):
        called.append(_verify_mcp_auth())
    middleware = MCPAuthMiddleware(downstream)
    async def receive():
        return {"type": "http.request", "body": b""}
    responses = []
    async def send(message):
        responses.append(message)
    for query in (b"api_key=secret-extra", b"other_api_key=secret"):
        await middleware({"type": "http", "headers": [], "query_string": query}, receive, send)
        assert responses[-2]["status"] == 403
    assert not called
    await middleware({"type": "http", "headers": [(b"authorization", b"Bearer secret")], "query_string": b""}, receive, send)
    assert called == [None]
    assert _verify_mcp_auth() is not None  # Request authorization cannot leak.


@pytest.mark.asyncio
async def test_mcp_http_bearer_authorizes_tool_without_duplicate_key(monkeypatch):
    from backend.app import mcp_asgi_app
    monkeypatch.setattr(settings, "API_KEY", "transport-secret")
    controller.env = SimulatedBuildingEnvironment(seed=42)
    await controller.step_simulation()
    headers = {"Authorization": "Bearer transport-secret", "Accept": "application/json, text/event-stream"}
    async with mcp_asgi_app.lifespan(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers=headers) as client:
            initialized = await client.post("/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "regression", "version": "1"}}})
            assert initialized.status_code == 200
            if "mcp-session-id" in initialized.headers:
                client.headers["mcp-session-id"] = initialized.headers["mcp-session-id"]
            await client.post("/mcp/", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
            response = await client.post("/mcp/", json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "update_setpoint", "arguments": {"zone": "Core", "cooling_c": 30, "heating_c": 16}}})
    assert response.status_code == 200
    import json
    payload = json.loads(next(line[6:] for line in response.text.splitlines() if line.startswith("data: ")))
    assert not payload["result"].get("isError", False), payload
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["success"], result
    assert result["cooling_c"] == 26


@pytest.mark.asyncio
async def test_energyplus_lifecycle_is_invoked():
    env = MagicMock(spec=EnergyPlusBuildingEnvironment)
    env.initialize = AsyncMock()
    env.close = AsyncMock()
    ctrl = AutonomousController()
    with patch("backend.controller.create_environment", return_value=env):
        await ctrl._initialise_environment()
    env.initialize.assert_awaited_once()
    await ctrl.stop()
    env.close.assert_awaited_once()


def test_application_lifespan_starts_simulator_and_flushes_run():
    from starlette.testclient import TestClient
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert controller._running
        response = client.post("/api/setpoint", json={"zone": "Core", "cooling": 30, "heating": 16})
        assert response.status_code == 200
        assert response.json()["success"]
    assert not controller._running
    assert not controller._persistence_tasks


@pytest.mark.asyncio
async def test_energyplus_does_not_return_stale_observation():
    env = EnergyPlusBuildingEnvironment.__new__(EnergyPlusBuildingEnvironment)
    env._delivered_step = 1
    env._latest_obs = SimpleNamespace(timestep=1)
    env._step_event = MagicMock()
    env._step_event.wait.return_value = False
    env._advance_event = threading.Event()
    env._lock = threading.RLock()
    env._error = None
    with pytest.raises(RuntimeError, match="new observation"):
        await env.step()


def test_energyplus_reads_meter_handles_and_accumulates_energy():
    env = EnergyPlusBuildingEnvironment.__new__(EnergyPlusBuildingEnvironment)
    exchange = MagicMock()
    exchange.api_data_fully_ready.return_value = True
    exchange.warmup_flag.return_value = False
    exchange.get_variable_value.side_effect = lambda state, handle: {1: 22.0, 2: 24.0, 3: 20.0, 4: 5.0}[handle]
    exchange.get_meter_value.return_value = 3_600_000
    exchange.year.return_value = 2024
    exchange.month.return_value = 1
    exchange.day_of_month.return_value = 1
    exchange.hour.return_value = 23
    exchange.zone_time_step_number.return_value = 4
    exchange.zone_time_step.return_value = 0.25
    env._api = SimpleNamespace(exchange=exchange)
    env._stopping = False
    env._handles_init = True
    env._lock = threading.RLock()
    env._temp_handles = dict.fromkeys(settings.ZONES, 1)
    env._cool_value_handles = dict.fromkeys(settings.ZONES, 2)
    env._heat_value_handles = dict.fromkeys(settings.ZONES, 3)
    env._outdoor_temp_handle = 4
    env._meter_handle = 5
    env._step_n = 0
    env._energy = 0.0
    env._step_event = threading.Event()
    env._ready_event = threading.Event()
    env._advance_event = MagicMock()
    env._timestep_callback(None)
    env._timestep_callback(None)
    exchange.get_meter_value.assert_called_with(None, 5)
    assert env._latest_obs.total_energy_kwh == 2.0
    assert env._latest_obs.hvac_power_kw == 4.0
    assert env._latest_obs.zones["Core"].setpoint_cooling == 24.0
    assert env._latest_obs.simulation_time.day == 2


def test_energyplus_rejects_missing_model_handles():
    env = EnergyPlusBuildingEnvironment.__new__(EnergyPlusBuildingEnvironment)
    exchange = MagicMock()
    exchange.get_variable_handle.return_value = -1
    exchange.get_actuator_handle.return_value = 1
    exchange.get_meter_handle.return_value = 2
    env._api = SimpleNamespace(exchange=exchange)
    env._temp_handles = {}
    env._cool_sp_handles = {}
    env._heat_sp_handles = {}
    env._cool_value_handles = {}
    env._heat_value_handles = {}
    with pytest.raises(RuntimeError, match="missing required"):
        env._init_handles(None)
    assert exchange.get_variable_handle.call_args_list[0].args[-1] == "Core Zone"


@pytest.mark.asyncio
async def test_mcp_benchmark_executes_live_mutations():
    from evaluate import eval_mcp_tools
    results = await eval_mcp_tools(repetitions=2)
    assert len(results) == 10
    assert all(result["status"] == "Success" for result in results)


@pytest.mark.asyncio
async def test_mcp_benchmark_marks_tool_error_as_failure():
    from evaluate import eval_mcp_tools
    with patch("evaluate.update_setpoint", AsyncMock(return_value={"success": False, "error": "rejected"})):
        results = await eval_mcp_tools(repetitions=1)
    assert next(r for r in results if r["name"] == "update_setpoint")["status"] == "Failed: rejected"


@pytest.mark.asyncio
async def test_old_database_gets_additive_migration():
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE historical_readings (id INTEGER PRIMARY KEY)"))
    await init_db()
    async with engine.begin() as conn:
        rows = await conn.execute(text("PRAGMA table_info(historical_readings)"))
        assert "baseline_power_kw" in [row[1] for row in rows]
