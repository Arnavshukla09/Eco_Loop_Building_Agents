"""Audit regressions: browser isolation, truthful controls, and adapter validation."""
import asyncio
from datetime import datetime
import math
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.app import app, MCPAuthMiddleware
from backend.auth import browser_origin_allowed, valid_api_key
from backend.controller import AutonomousController, controller
from backend.database import init_db
from backend.energyplus_runner import SimulatedBuildingEnvironment, OccupancySchedule, WeatherModel, ZONE_AREA
from backend.forecast import electricity_rate, forecast_conditions
from backend.hardware import BACnetMonitor, ModbusPoint, ModbusMonitor
from backend.llm_agent import _rule_based_decision, BuildingAIAgent
from backend.models import SetpointCommand
from backend.providers import ForecastProvider, RuleBasedProvider, ScheduledProvider
from backend.repository import repository
from backend.state import state_store
from config.settings import Settings, settings


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/simulation/reset", "/api/simulation/speed?speedup=3600", "/api/override/release", "/mcp/"])
async def test_untrusted_browser_cannot_mutate_without_credentials(path):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(path, headers={"Origin": "https://attacker.invalid"})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_wildcard_cors_does_not_grant_browser_control(monkeypatch):
    monkeypatch.setattr(settings, "CORS_ORIGINS", ["*"])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/simulation/speed?speedup=3600", headers={"Origin": "https://attacker.invalid"})
    assert response.status_code == 403
    assert settings.SPEEDUP_FACTOR != 3600


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["http://localhost:8011", "http://localhost:5173", "http://127.0.0.1:5174"])
async def test_dashboard_origin_can_control(origin):
    previous = settings.SPEEDUP_FACTOR
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost:8011") as client:
            response = await client.post("/api/simulation/speed?speedup=60", headers={"Origin": origin})
        assert response.status_code == 200
    finally:
        settings.SPEEDUP_FACTOR = previous


def test_untrusted_websocket_is_rejected_before_accept():
    # No lifespan is needed to verify the handshake rejection.
    with pytest.raises(WebSocketDisconnect) as error:
        with TestClient(app).websocket_connect("/ws", headers={"Origin": "https://attacker.invalid"}):
            pass
    assert error.value.code == 1008


def test_null_origin_is_not_a_trusted_browser():
    assert not browser_origin_allowed("null", {"scheme": "http", "headers": [(b"host", b"test")]})


def test_same_origin_attacker_host_does_not_bypass_origin_check():
    assert not browser_origin_allowed("http://rebind.attacker.invalid", {"scheme": "http", "headers": [(b"host", b"rebind.attacker.invalid")]})


def test_explicit_deployment_origin_is_accepted(monkeypatch):
    monkeypatch.setattr(settings, "CORS_ORIGINS", ["https://building.example"])
    assert browser_origin_allowed("https://building.example", {"scheme": "http", "headers": [(b"host", b"internal:8000")]})


@pytest.mark.asyncio
async def test_mcp_keys_in_urls_do_not_authenticate(monkeypatch):
    monkeypatch.setattr(settings, "API_KEY", "secret")
    downstream = AsyncMock()
    messages = []
    async def send(message):
        messages.append(message)
    await MCPAuthMiddleware(downstream)({"type": "http", "headers": [], "query_string": b"api_key=secret"}, AsyncMock(), send)
    assert messages[0]["status"] == 403
    downstream.assert_not_awaited()


def test_api_key_comparison_supports_unicode(monkeypatch):
    monkeypatch.setattr(settings, "API_KEY", "secret-\u03b1")
    assert valid_api_key("secret-\u03b1")
    assert not valid_api_key("secret-\u03b2")
    assert not valid_api_key(None)


def test_environment_typo_is_rejected():
    with pytest.raises(ValueError):
        Settings(_env_file=None, ENVIRONMENT="prodution")


def test_agent_construction_does_not_probe_network():
    with patch("ollama.Client.list") as probe:
        assert not BuildingAIAgent().is_available
    probe.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", [RuleBasedProvider, ForecastProvider, ScheduledProvider])
async def test_deterministic_provider_is_healthy_without_ollama(provider):
    controller.provider = provider()
    controller.env = SimulatedBuildingEnvironment(seed=42)
    obs = await controller.step_simulation()
    state_store.set_simulation_running(True)
    state_store.update_decision(await controller.provider.decide(obs))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        data = (await client.get("/api/health")).json()
    assert data["status"] == "ok"
    assert data["controller_mode"] == controller.provider.name
    assert not data["llm_available"]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", [None, RuleBasedProvider, ForecastProvider, ScheduledProvider])
async def test_fallback_health_reports_actual_source(provider):
    if provider is not None:
        controller.provider = provider()
    controller.env = SimulatedBuildingEnvironment(seed=42)
    obs = await controller.step_simulation()
    state_store.set_simulation_running(True)
    decision = _rule_based_decision(obs)
    decision.controller_source = "fallback"
    state_store.update_decision(decision)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        data = (await client.get("/api/health")).json()
    assert data["controller_mode"] == "fallback"
    assert data["status"] == "degraded"


def test_default_hold_duration_uses_configuration(monkeypatch):
    monkeypatch.setattr(settings, "MANUAL_OVERRIDE_MINUTES", 90)
    assert SetpointCommand(cooling=24, heating=20).duration_minutes == 90
    assert SetpointCommand(cooling=24, heating=20, duration_minutes=30).duration_minutes == 30


@pytest.mark.asyncio
async def test_reset_drops_reference_that_misses_first_step():
    ctrl = AutonomousController()
    await ctrl._initialise_environment()
    await ctrl.step_simulation()
    initialise = ctrl._initialise_environment
    async def failing_reference():
        await initialise()
        ctrl.baseline_env.step = AsyncMock(side_effect=RuntimeError("lost first reference step"))
    with patch.object(ctrl, "_initialise_environment", side_effect=failing_reference):
        await ctrl.reset_simulation()
    assert ctrl.baseline_env is None
    assert state_store.get_metrics().baseline_mode == "unmeasured"
    await ctrl.step_simulation()
    assert state_store.get_metrics().baseline_mode == "unmeasured"


@pytest.mark.asyncio
async def test_applied_and_requested_decision_values_are_both_retained():
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
    record = (await repository.get_decisions(ctrl._current_run_id))[0]
    assert record["requested_setpoints"]["Core"] == {"cooling": 30, "heating": 16}
    assert record["applied_setpoints"]["Core"] == {"cooling": 26, "heating": 18}


@pytest.mark.asyncio
async def test_held_decisions_are_not_audited_as_failed():
    await init_db()
    ctrl = AutonomousController()
    ctrl.env = SimulatedBuildingEnvironment(seed=42)
    obs = await ctrl.step_simulation()
    ctrl._current_run_id = await repository.create_run()
    await ctrl.manual_override(None, 25, 19, 60)
    await ctrl._apply_decision(_rule_based_decision(obs))
    await asyncio.gather(*tuple(ctrl._persistence_tasks))
    record = (await repository.get_decisions(ctrl._current_run_id))[0]
    assert record["status"] == "held"
    assert record["applied_setpoints"] == {}


@pytest.mark.asyncio
async def test_one_failed_actuator_does_not_prevent_other_zones():
    ctrl = AutonomousController()
    ctrl.env = SimulatedBuildingEnvironment(seed=42)
    obs = await ctrl.step_simulation()
    real_setpoint = ctrl.env.set_setpoint
    async def actuate(zone, cool, heat):
        if zone == "Core":
            raise OSError("actuator offline")
        return await real_setpoint(zone, cool, heat)
    decision = _rule_based_decision(obs)
    with patch.object(ctrl.env, "set_setpoint", side_effect=actuate):
        assert await ctrl._apply_decision(decision)
    assert "Core" not in decision.applied_setpoints
    assert len(decision.applied_setpoints) == len(settings.ZONES) - 1


@pytest.mark.asyncio
async def test_manual_hold_expires_and_allows_agent_again():
    ctrl = AutonomousController()
    ctrl.env = SimulatedBuildingEnvironment(seed=42)
    obs = await ctrl.step_simulation()
    await ctrl.manual_override("Core", 25, 19, 15)
    decision = _rule_based_decision(obs)
    await ctrl._apply_decision(decision)
    assert "Core" not in decision.applied_setpoints
    obs = await ctrl.step_simulation()
    assert not ctrl.control_status()["overrides"]
    decision = _rule_based_decision(obs)
    await ctrl._apply_decision(decision)
    assert "Core" in decision.applied_setpoints


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
async def test_sensor_fault_does_not_break_strict_json_responses(bad):
    controller.env = SimulatedBuildingEnvironment(seed=42)
    controller.env.inject_sensor_fault("Core", bad)
    await controller.step_simulation()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/status")
    assert response.status_code == 200
    zone = response.json()["building"]["zones"]["Core"]
    assert zone["sensor_fault"]
    assert zone["raw_temperature"] is None
    assert math.isfinite(zone["temperature"])


@pytest.mark.asyncio
async def test_fan_energy_and_ventilation_are_physical_and_accounted():
    low = SimulatedBuildingEnvironment(seed=42)
    high = SimulatedBuildingEnvironment(seed=42)
    for env in (low, high):
        env.inject_occupancy_override(1)
        env.inject_weather_override(21)
    assert await low.set_fan_speed("low")
    assert await high.set_fan_speed("high")
    low_obs, high_obs = await low.step(), await high.step()
    area = sum(ZONE_AREA.values())
    minimum_outdoor_flow = area * 0.0003 + area * 0.07 * 0.0025
    assert low_obs.ventilation_m3s >= minimum_outdoor_flow
    assert low_obs.fan_power_kw < high_obs.fan_power_kw
    assert low_obs.total_energy_kwh < high_obs.total_energy_kwh
    assert high_obs.fan_power_kw <= high_obs.hvac_power_kw
    assert high_obs.total_energy_kwh == pytest.approx(high_obs.hvac_power_kw * settings.TIMESTEP_MINUTES / 60, abs=0.003)
    assert high_obs.total_cost == pytest.approx(high_obs.total_energy_kwh * high_obs.electricity_rate, abs=0.001)


@pytest.mark.asyncio
async def test_fan_model_disabled_has_no_fan_energy(monkeypatch):
    monkeypatch.setattr(settings, "FAN_MODEL_ENABLED", False)
    obs = await SimulatedBuildingEnvironment(seed=42).step()
    assert obs.fan_power_kw == obs.ventilation_m3s == 0
    reference = SimulatedBuildingEnvironment(is_baseline=True)
    assert not await reference.set_fan_speed("low")


def test_forecast_matches_weather_expectation_without_consuming_randomness():
    dt = datetime(2024, 7, 15, 6, 45)
    weather = WeatherModel(seed=42)
    rng_before = weather._rng.getstate()
    forecast = forecast_conditions(dt, OccupancySchedule())
    assert weather._rng.getstate() == rng_before
    assert len(forecast) == 6
    with patch.object(weather._rng, "gauss", return_value=0):
        for point in forecast:
            time = datetime.fromisoformat(point["time"])
            expected, _ = weather.get_conditions(time)
            assert point["outdoor_temp"] == pytest.approx(expected, abs=0.005)
            assert point["occupancy"] == pytest.approx(OccupancySchedule().get(time), abs=0.0005)


def test_tariff_handles_peak_boundaries_overnight_and_weekends(monkeypatch):
    monkeypatch.setattr(settings, "TARIFF_PEAK_START", 16)
    monkeypatch.setattr(settings, "TARIFF_PEAK_END", 21)
    assert electricity_rate(datetime(2024, 1, 1, 16)) == settings.TARIFF_PEAK
    assert electricity_rate(datetime(2024, 1, 1, 21)) == settings.TARIFF_OFFPEAK
    assert electricity_rate(datetime(2024, 1, 6, 16)) == settings.TARIFF_OFFPEAK
    monkeypatch.setattr(settings, "TARIFF_PEAK_START", 22)
    monkeypatch.setattr(settings, "TARIFF_PEAK_END", 6)
    assert electricity_rate(datetime(2024, 1, 1, 23)) == settings.TARIFF_PEAK
    assert electricity_rate(datetime(2024, 1, 2, 5)) == settings.TARIFF_PEAK
    assert electricity_rate(datetime(2024, 1, 2, 6)) == settings.TARIFF_OFFPEAK


@pytest.mark.asyncio
async def test_forecast_provider_prepares_comfort_before_occupancy():
    env = SimulatedBuildingEnvironment(seed=42, start_time=datetime(2024, 1, 1, 6))
    obs = await env.step()
    scheduled = await ScheduledProvider().decide(obs)
    forecast = await ForecastProvider().decide(obs)
    assert obs.occupancy < 0.2
    assert scheduled.zone_setpoints["Core"].cooling == 28
    assert forecast.zone_setpoints["Core"].cooling == 24
    assert forecast.zone_setpoints["Core"].heating == 20.5


@pytest.mark.parametrize("register_type", ["typo", "coil"])
def test_modbus_point_rejects_wrong_register_bank(register_type):
    with pytest.raises(ValueError):
        ModbusPoint("temperature", 1, register_type=register_type)


@pytest.mark.asyncio
@pytest.mark.parametrize("scale,offset", [(float("inf"), 0), (1, float("nan")), (1e308, 0)])
async def test_bacnet_rejects_nonfinite_scaled_telemetry(scale, offset):
    monitor = BACnetMonitor("configured-only", {"zone": {"object": "analog-input,1", "scale": scale, "offset": offset}})
    application = AsyncMock()
    application.read_property.return_value = 25
    with pytest.raises(ValueError, match="Nonfinite"):
        await monitor.sample(application)


def test_modbus_monitor_closes_connection_on_read_failure():
    from unittest.mock import MagicMock
    client = MagicMock()
    client.connect.return_value = True
    client.read_holding_registers.return_value.isError.return_value = True
    monitor = ModbusMonitor("configured-only", [ModbusPoint("zone", 1)])
    with pytest.raises(ValueError):
        monitor.sample(client_factory=lambda *args, **kwargs: client)
    client.close.assert_called_once()
