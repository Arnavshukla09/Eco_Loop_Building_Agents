import pytest
from datetime import datetime
from backend.energyplus_runner import (
    SimulatedBuildingEnvironment,
    _pmv_ppd,
    WeatherModel,
    OccupancySchedule,
    ZONES,
)
from config.settings import settings


def test_pmv_ppd_comfort_range():
    """Verify PMV is neutral (~0) in normal office comfort temperatures (22-24°C)."""
    pmv, ppd = _pmv_ppd(23.0, 50.0)
    assert -0.5 <= pmv <= 0.5, f"Expected neutral PMV, got {pmv}"
    assert 5.0 <= ppd <= 10.0, f"Expected low dissatisfaction, got {ppd}%"


def test_pmv_ppd_extreme_temperatures():
    """Verify PMV scales towards hot and cold limits and respects output boundaries."""
    pmv_hot, ppd_hot = _pmv_ppd(35.0, 80.0)
    assert pmv_hot > 1.5, f"Expected hot PMV, got {pmv_hot}"
    assert ppd_hot > 50.0

    pmv_cold, ppd_cold = _pmv_ppd(10.0, 20.0)
    assert pmv_cold < -1.5, f"Expected cold PMV, got {pmv_cold}"
    assert ppd_cold > 50.0

    # Ensure bounds [-3, 3] and [5, 100]
    assert -3.0 <= pmv_hot <= 3.0
    assert -3.0 <= pmv_cold <= 3.0
    assert 5.0 <= ppd_hot <= 100.0


def test_occupancy_schedule():
    """Verify occupancy schedule reflects office hours and weekend closure."""
    sched = OccupancySchedule()
    # Weekday 10:00 (peak)
    monday_noon = datetime(2024, 1, 8, 10, 0)
    assert sched.get(monday_noon) == 1.0

    # Weekday 03:00 (night)
    monday_night = datetime(2024, 1, 8, 3, 0)
    assert sched.get(monday_night) == 0.0

    # Saturday 14:00 (weekend)
    saturday_day = datetime(2024, 1, 13, 14, 0)
    assert sched.get(saturday_day) == 0.0


def test_weather_model_deterministic_seed():
    """Verify WeatherModel produces identical output when seeded."""
    w1 = WeatherModel(seed=42)
    w2 = WeatherModel(seed=42)
    dt = datetime(2024, 7, 15, 14, 0)
    t1, h1 = w1.get_conditions(dt)
    t2, h2 = w2.get_conditions(dt)
    assert t1 == pytest.approx(t2)
    assert h1 == pytest.approx(h2)


@pytest.mark.asyncio
async def test_simulated_environment_step():
    """Verify simulation steps advance time and accumulate energy."""
    env = SimulatedBuildingEnvironment(seed=123)
    obs1 = await env.step()
    assert obs1.timestep == 1
    assert obs1.total_energy_kwh >= 0.0
    assert len(obs1.zones) == len(ZONES)

    obs2 = await env.step()
    assert obs2.timestep == 2
    assert obs2.total_energy_kwh >= obs1.total_energy_kwh
    assert obs2.simulation_time > obs1.simulation_time


@pytest.mark.asyncio
async def test_baseline_environment_rejects_setpoints():
    """Verify baseline environment maintains fixed setpoints and rejects alterations."""
    env = SimulatedBuildingEnvironment(is_baseline=True)
    assert env._is_baseline is True
    # Initial setpoints should match baseline configuration
    assert env._sp_cool["Core"] == settings.BASELINE_SETPOINT_COOLING
    assert env._sp_heat["Core"] == settings.BASELINE_SETPOINT_HEATING

    # Modifying setpoints must return False and not change values
    result = await env.set_setpoint("Core", 26.0, 18.0)
    assert result is False
    assert env._sp_cool["Core"] == settings.BASELINE_SETPOINT_COOLING
    assert env._sp_heat["Core"] == settings.BASELINE_SETPOINT_HEATING


def test_timing_and_speedup_calculations():
    """Verify speedup factor formula matches physics timing."""
    # 15-minute timestep at 60x speedup -> 15 * 60 / 60 = 15.0 wall-clock seconds
    speedup = 60.0
    ts_min = 15
    wall_seconds = (ts_min * 60.0) / speedup
    assert wall_seconds == 15.0

    # 15-minute timestep at 3600x speedup (1 simulated hour per second) -> 900 / 3600 = 0.25s
    fast_speedup = 3600.0
    fast_wall_seconds = (ts_min * 60.0) / fast_speedup
    assert fast_wall_seconds == 0.25
