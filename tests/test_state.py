import pytest
from datetime import datetime, timezone
from backend.models import BuildingObservation, ZoneState, AgentDecision, ZoneSetpoint
from backend.state import BuildingStateStore, CO2_KG_PER_KWH
from config.settings import settings


@pytest.fixture
def test_store():
    return BuildingStateStore()


@pytest.fixture
def sample_obs():
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
    return BuildingObservation(
        timestamp=datetime.now(timezone.utc),
        simulation_time=datetime(2024, 1, 15, 12, 0),
        zones=zones,
        outdoor_temp=15.0,
        outdoor_humidity=55.0,
        total_energy_kwh=100.0,
        hvac_power_kw=10.0,
        occupancy=0.7,
        timestep=1,
    )


def test_observation_update_and_history(test_store, sample_obs):
    """Verify state store records observation, computes metrics, and appends history."""
    test_store.update_observation(sample_obs)
    retrieved = test_store.get_observation()
    assert retrieved is not None
    assert retrieved.timestep == 1
    assert retrieved.total_energy_kwh == 100.0

    history = test_store.get_history()
    assert len(history) == 1
    assert history[0].total_energy_kwh == 100.0


def test_measured_baseline_savings(test_store, sample_obs):
    """Verify energy savings formula with measured baseline."""
    # Suppose measured baseline used 120 kWh, AI used 100 kWh
    test_store.update_baseline_energy(120.0)
    test_store.update_observation(sample_obs)

    metrics = test_store.get_metrics()
    assert metrics is not None
    assert metrics.baseline_mode == "measured"
    assert metrics.baseline_energy_kwh == 120.0
    assert metrics.current_energy_kwh == 100.0
    # Expected savings: (120 - 100) / 120 * 100 = 16.67%
    assert metrics.energy_savings_pct == pytest.approx(16.67, abs=0.01)
    # CO2 saved = 20 kWh * 0.386
    expected_co2 = 20.0 * CO2_KG_PER_KWH
    assert metrics.co2_saved_kg == pytest.approx(expected_co2, abs=0.01)


def test_unmeasured_baseline_labels_correctly(test_store, sample_obs):
    """Verify that when baseline has not been measured, metrics are clearly labeled."""
    # Baseline is 0.0 (unmeasured)
    test_store.update_observation(sample_obs)
    metrics = test_store.get_metrics()
    assert metrics is not None
    assert metrics.baseline_mode == "unmeasured"
    assert metrics.energy_savings_pct == 0.0


def test_history_max_length(test_store, sample_obs):
    """Verify history deque honors maximum length."""
    for i in range(10):
        obs = sample_obs.model_copy(update={"timestep": i})
        test_store.update_observation(obs)

    assert len(test_store.get_history(limit=5)) == 5
    assert len(test_store.get_history(limit=100)) == 10
