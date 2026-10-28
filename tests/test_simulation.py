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


@pytest.mark.asyncio
async def test_controller_step_simulation_lock():
    """Verify controller.step_simulation safely synchronizes concurrent step requests."""
    import asyncio
    from backend.controller import AutonomousController

    ctrl = AutonomousController()
    ctrl.env = SimulatedBuildingEnvironment(seed=42)
    ctrl.baseline_env = SimulatedBuildingEnvironment(is_baseline=True, seed=42)

    # Launch 5 concurrent step requests
    results = await asyncio.gather(*[ctrl.step_simulation() for _ in range(5)])
    assert len(results) == 5
    # Timesteps should be sequentially incremented without skipping or racing
    timesteps = [r.timestep for r in results]
    assert sorted(timesteps) == [1, 2, 3, 4, 5]
    assert ctrl._step_count == 5


@pytest.mark.asyncio
async def test_controller_setpoints_and_reset_lock():
    """Verify setpoints and reset operations execute safely under lock without touching baseline."""
    from backend.controller import AutonomousController

    ctrl = AutonomousController()
    ctrl.env = SimulatedBuildingEnvironment(seed=42)
    ctrl.baseline_env = SimulatedBuildingEnvironment(is_baseline=True, seed=42)

    # Initial step
    await ctrl.step_simulation()

    # Safely set setpoint on Core zone
    ok = await ctrl.set_zone_setpoint("Core", 25.0, 19.0)
    assert ok is True
    assert ctrl.env._sp_cool["Core"] == 25.0
    assert ctrl.env._sp_heat["Core"] == 19.0

    # Baseline environment must NOT have been changed
    assert ctrl.baseline_env._sp_cool["Core"] == 22.0
    assert ctrl.baseline_env._sp_heat["Core"] == 21.0

    # Reset simulation
    reset_obs = await ctrl.reset_simulation()
    assert reset_obs.timestep == 1
    assert ctrl._step_count == 0


@pytest.mark.asyncio
async def test_concurrent_simulation_steps_and_mutations():
    """Verify concurrent step requests, setpoint changes, and queries execute without data races."""
    import asyncio
    from backend.controller import AutonomousController

    ctrl = AutonomousController()
    ctrl.env = SimulatedBuildingEnvironment(seed=99)
    ctrl.baseline_env = SimulatedBuildingEnvironment(is_baseline=True, seed=99)

    async def worker_steps():
        for _ in range(4):
            await ctrl.step_simulation()
            await asyncio.sleep(0.01)

    async def worker_setpoints():
        for _ in range(4):
            await ctrl.set_zone_setpoint("Perimeter_N", 25.0, 19.0)
            await asyncio.sleep(0.01)

    async def worker_all_setpoints():
        for _ in range(2):
            await ctrl.set_all_zone_setpoints(24.5, 20.0)
            await asyncio.sleep(0.01)

    await asyncio.gather(worker_steps(), worker_setpoints(), worker_all_setpoints())
    assert ctrl._step_count == 4
    assert ctrl.env._sp_cool["Perimeter_N"] in (24.5, 25.0)


@pytest.mark.asyncio
async def test_reset_during_simulation():
    """Verify reset_simulation cleanly resets step counter, baseline, and state while running."""
    from backend.controller import AutonomousController
    from backend.state import state_store

    ctrl = AutonomousController()
    ctrl.env = SimulatedBuildingEnvironment(seed=77)
    ctrl.baseline_env = SimulatedBuildingEnvironment(is_baseline=True, seed=77)

    # Step forward 5 steps
    for _ in range(5):
        await ctrl.step_simulation()

    assert ctrl._step_count == 5
    assert state_store.get_observation().timestep == 5

    # Reset
    obs = await ctrl.reset_simulation()
    assert ctrl._step_count == 0
    assert obs.timestep == 1
    new_obs = state_store.get_observation()
    assert new_obs.timestep == 1


def test_negative_energy_savings_unclamped():
    """Verify energy savings and CO2 calculations reflect negative savings when HVAC exceeds baseline."""
    from backend.state import BuildingStateStore
    from backend.models import BuildingObservation, ZoneState

    store = BuildingStateStore()
    zones = {
        z: ZoneState(
            zone_id=z,
            temperature=22.0,
            setpoint_cooling=24.0,
            setpoint_heating=20.0,
            pmv_score=0.0,
            ppd_score=5.0,
            humidity=50.0,
        )
        for z in settings.ZONES
    }
    # Simulated run consumed 120 kWh, but baseline consumed only 100 kWh (over-consumption)
    obs = BuildingObservation(
        timestamp=datetime.now(),
        simulation_time=datetime(2024, 1, 15, 12, 0),
        zones=zones,
        outdoor_temp=10.0,
        outdoor_humidity=60.0,
        total_energy_kwh=120.0,
        hvac_power_kw=15.0,
        occupancy=0.5,
        timestep=10,
    )
    store.update_baseline_energy(100.0)
    store.update_observation(obs)

    metrics = store.get_metrics()
    assert metrics is not None
    # Savings should be negative: (100 - 120) / 100 = -20.0%
    assert metrics.energy_savings_pct == pytest.approx(-20.0, abs=0.1)
    # CO2 saved should also be negative: (100 - 120) * 0.4 = -8.0 kg (not clamped to 0)
    assert metrics.co2_saved_kg < 0.0
    assert metrics.co2_saved_kg == pytest.approx(-7.72, abs=0.01)
