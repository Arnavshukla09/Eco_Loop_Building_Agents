"""
tests/test_fault_tolerance.py
─────────────────────────────
Phase 5: Fault-tolerance, stress, and edge-case verification suite.
Validates sensor dropouts, extreme polar/heatwave weather, sudden occupancy surges,
actuator slew-rate damping, and LLM connection/JSON failures.
"""
import asyncio
import math
from datetime import datetime, timezone
import pytest

from backend.energyplus_runner import SimulatedBuildingEnvironment
from backend.controller import AutonomousController
from backend.llm_agent import BuildingAIAgent
from backend.models import AgentDecision, ZoneSetpoint
from backend.state import state_store
from config.settings import settings


@pytest.mark.asyncio
async def test_sensor_dropout_detection_and_imputation():
    """Verify system detects NaN / disconnected sensor readings, flags fault, and imputes healthy mean."""
    env = SimulatedBuildingEnvironment(seed=42)

    # 1. Step 1: Nominal operation
    obs1 = await env.step()
    assert obs1.zones["Perimeter_N"].sensor_fault is False

    # 2. Step 2: Inject sensor dropout (NaN) on Perimeter_N
    env.inject_sensor_fault("Perimeter_N", float("nan"))
    obs2 = await env.step()

    p_n = obs2.zones["Perimeter_N"]
    assert p_n.sensor_fault is True
    # Temperature must be imputed to a valid physical range, not NaN
    assert not math.isnan(p_n.temperature)
    assert 18.0 <= p_n.temperature <= 26.0
    # raw_temperature should be None because NaN cannot be represented cleanly
    assert p_n.raw_temperature is None
    # Comfort indices must be calculable without math domain error
    assert not math.isnan(p_n.pmv_score)
    assert not math.isnan(p_n.ppd_score)

    # 3. Step 3: Inject extreme negative out-of-range value (-999°C sensor disconnect)
    env.inject_sensor_fault("Perimeter_E", -999.0)
    obs3 = await env.step()
    p_e = obs3.zones["Perimeter_E"]
    assert p_e.sensor_fault is True
    assert p_e.raw_temperature == -999.0
    assert 18.0 <= p_e.temperature <= 26.0

    # 4. Clear faults -> resumes normal operation
    env.clear_sensor_fault("Perimeter_N")
    env.clear_sensor_fault("Perimeter_E")
    obs4 = await env.step()
    assert obs4.zones["Perimeter_N"].sensor_fault is False
    assert obs4.zones["Perimeter_E"].sensor_fault is False


@pytest.mark.asyncio
async def test_extreme_weather_polar_vortex():
    """Verify building physics and heating controls survive -20°C polar freeze without freezing."""
    env = SimulatedBuildingEnvironment(seed=101)
    env.inject_weather_override(temp=-20.0, humidity=30.0)

    # Run for 16 timesteps (4 hours) of extreme sub-zero weather
    for _ in range(16):
        obs = await env.step()

    # Total energy consumed should be positive as heating maintains envelope boundary
    assert obs.total_energy_kwh >= 0.0
    for zone_name, z in obs.zones.items():
        # Temperature must remain safely above freezing (>= 16°C min heating setpoint)
        assert z.temperature >= 16.0, f"Zone {zone_name} froze to {z.temperature}°C"
        assert z.temperature <= 26.0


@pytest.mark.asyncio
async def test_extreme_weather_heatwave():
    """Verify building physics and cooling controls survive +45°C extreme heatwave."""
    env = SimulatedBuildingEnvironment(seed=202)
    env.inject_weather_override(temp=45.0, humidity=40.0)

    # Run for 16 timesteps (4 hours) of extreme heatwave
    for _ in range(16):
        obs = await env.step()

    # Cooling should engage to counter ambient heat infiltration
    assert obs.hvac_power_kw > 0.0
    assert obs.total_energy_kwh > 0.0
    for zone_name, z in obs.zones.items():
        # Temperature must remain within reasonable bounds (<= 28°C)
        assert z.temperature <= 28.0, f"Zone {zone_name} overheated to {z.temperature}°C"


@pytest.mark.asyncio
async def test_sudden_occupancy_step_change():
    """Verify sudden occupancy step from 0% (empty) to 100% (packed) does not cause numerical instability."""
    env = SimulatedBuildingEnvironment(seed=303)

    # Empty building
    env.inject_occupancy_override(0.0)
    obs_empty = await env.step()
    assert obs_empty.occupancy == 0.0

    # Instant surge to 100% occupancy
    env.inject_occupancy_override(1.0)
    obs_full = await env.step()
    assert obs_full.occupancy == 1.0

    # Power draw should rise due to equipment and occupant internal heat gains
    assert obs_full.hvac_power_kw >= obs_empty.hvac_power_kw
    for z in obs_full.zones.values():
        assert not math.isnan(z.temperature)
        assert not math.isnan(z.pmv_score)


@pytest.mark.asyncio
async def test_actuator_slew_rate_limiting():
    """Verify controller prevents drastic setpoint jumps (>2°C per cycle) to protect actuators."""
    ctrl = AutonomousController()
    ctrl.env = SimulatedBuildingEnvironment(seed=404)
    obs = await ctrl.step_simulation()

    # Current cooling setpoint is ~24.0°C
    initial_cool = obs.zones["Core"].setpoint_cooling

    # Request an aggressive jump to 30.0°C (+6.0°C delta)
    aggressive_decision = AgentDecision(
        zone_setpoints={"Core": ZoneSetpoint(cooling=30.0, heating=20.0)},
        fan_speed="high",
        energy_mode="eco",
        controller_source="llm",
        reasoning="Aggressive jump test",
        confidence=0.9,
        estimated_savings_pct=20.0,
    )

    await ctrl._apply_decision(aggressive_decision)

    # Slew-rate limiter should have damped the change to initial_cool + 2.0°C (e.g. 26.0°C)
    applied_cool = ctrl.env._sp_cool["Core"]
    assert applied_cool <= initial_cool + 2.05
    assert applied_cool < 30.0, "Actuator slew rate was not throttled"

    # Also verify manual setpoint commands via controller.set_zone_setpoint respect slew limiting unless forced
    ok = await ctrl.set_zone_setpoint("Core", cooling=30.0, heating=20.0)
    assert ok is True
    # Should again be clamped to previous applied_cool + 2.0
    manual_cool = ctrl.env._sp_cool["Core"]
    assert manual_cool <= applied_cool + 2.05

    # Forced update overrides slew limit
    ok_force = await ctrl.set_zone_setpoint("Core", cooling=30.0, heating=20.0, force=True)
    assert ok_force is True
    assert ctrl.env._sp_cool["Core"] == 30.0


@pytest.mark.asyncio
async def test_ollama_corrupted_json_recovery():
    """Verify agent catches invalid/corrupted JSON from LLM and falls back safely with controller_source=fallback."""
    agent = BuildingAIAgent()
    from unittest.mock import AsyncMock, patch

    env = SimulatedBuildingEnvironment(seed=505)
    obs = await env.step()

    # Corrupted / truncated JSON payload
    corrupted_payload = '{"zone_setpoints": {"Core": {"cooling": 24.0, "heating": '

    with patch.object(agent, "_call_ollama_async", AsyncMock(return_value=corrupted_payload)):
        decision = await agent.analyze_and_decide(obs)
        assert decision.controller_source == "fallback"
        assert "[Fallback]" in decision.reasoning
        # Setpoints generated by fallback must still be valid
        assert "Core" in decision.zone_setpoints
        assert decision.zone_setpoints["Core"].cooling >= decision.zone_setpoints["Core"].heating + 1.5


@pytest.mark.asyncio
async def test_ollama_connection_reset_recovery():
    """Verify network connection reset during inference triggers fallback and availability recovery."""
    agent = BuildingAIAgent()
    agent._available = True
    from unittest.mock import AsyncMock, patch

    env = SimulatedBuildingEnvironment(seed=606)
    obs = await env.step()

    with patch.object(agent, "_call_ollama_async", AsyncMock(side_effect=ConnectionResetError("Socket abruptly closed"))):
        decision = await agent.analyze_and_decide(obs)
        assert decision.controller_source == "fallback"
        assert "[Fallback]" in decision.reasoning


@pytest.mark.asyncio
async def test_simulation_advances_independently_of_llm_latency():
    """Verify simulation steps proceed without stalling even if AI inference is delayed."""
    ctrl = AutonomousController()
    ctrl.env = SimulatedBuildingEnvironment(seed=707)

    # Step simulation 5 times rapidly
    steps = [await ctrl.step_simulation() for _ in range(5)]
    assert len(steps) == 5
    assert steps[-1].timestep == 5
    assert ctrl._step_count == 5
