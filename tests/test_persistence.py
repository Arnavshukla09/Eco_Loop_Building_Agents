"""
tests/test_persistence.py
─────────────────────────
Automated tests for Phase 4: Database persistence layer, run archiving,
history recovery, and AI provider abstraction.
"""
from datetime import datetime, timezone
import pytest
import httpx

from backend.app import app
from backend.database import close_db, init_db
from backend.models import AgentDecision, BuildingObservation, HistoryEntry, ZoneSetpoint, ZoneState
from backend.providers import BaseDecisionProvider, OllamaProvider, RuleBasedProvider
from backend.repository import repository
from config.settings import settings


@pytest.fixture(autouse=True)
async def setup_test_db():
    await init_db()
    yield
    # Cleanup


@pytest.mark.asyncio
async def test_database_initialization_and_schema():
    """Verify database schema initializes cleanly and creates required tables."""
    run_id = await repository.create_run(baseline_mode="measured")
    assert run_id.startswith("run_")

    active_id = await repository.get_active_run_id()
    assert active_id == run_id


@pytest.mark.asyncio
async def test_run_lifecycle_recording_and_archival():
    """Verify full run lifecycle: creation -> readings -> decision logging -> completion."""
    run_id = await repository.create_run()

    # 1. Record telemetry reading
    entry = HistoryEntry(
        sim_time=datetime(2024, 1, 15, 14, 0, tzinfo=timezone.utc),
        wall_time=datetime.now(timezone.utc),
        avg_temp=22.3,
        hvac_power_kw=11.2,
        total_energy_kwh=88.5,
        comfort_score=0.91,
        energy_savings_pct=16.8,
        outdoor_temp=14.0,
        occupancy=0.75,
        ai_energy_mode="eco",
    )
    await repository.record_reading(run_id, entry, timestep=10)

    # 2. Record decision audit entry
    decision = AgentDecision(
        zone_setpoints={"Core": ZoneSetpoint(cooling=24.5, heating=20.0)},
        fan_speed="medium",
        energy_mode="eco",
        controller_source="llm",
        reasoning="Test decision log",
        confidence=0.9,
        estimated_savings_pct=15.0,
    )
    await repository.record_decision(run_id, decision, timestep=10)

    # 3. Retrieve history by run_id
    history = await repository.get_history(run_id=run_id)
    assert len(history) == 1
    assert history[0].avg_temp == 22.3
    assert history[0].energy_savings_pct == 16.8

    # 4. Complete run and verify summary record
    await repository.complete_run(
        run_id=run_id,
        total_steps=10,
        total_energy=88.5,
        baseline_energy=106.4,
        savings_pct=16.8,
        comfort_score=0.91,
    )

    runs = await repository.list_runs()
    assert len(runs) >= 1
    matching_run = next((r for r in runs if r["id"] == run_id), None)
    assert matching_run is not None
    assert matching_run["is_active"] is False
    assert matching_run["total_steps"] == 10
    assert matching_run["final_savings_pct"] == 16.8


@pytest.mark.asyncio
async def test_reset_preserves_previous_runs_in_database():
    """Verify simulation reset creates a new run while archiving previous runs in the DB."""
    from backend.controller import controller
    from backend.energyplus_runner import SimulatedBuildingEnvironment

    if controller.env is None:
        controller.env = SimulatedBuildingEnvironment(seed=42)
        controller.baseline_env = SimulatedBuildingEnvironment(is_baseline=True, seed=42)

    controller._current_run_id = await repository.create_run()
    run1_id = controller._current_run_id

    # Step simulation 3 times
    for _ in range(3):
        await controller.step_simulation()

    # Reset simulation
    await controller.reset_simulation()
    run2_id = controller._current_run_id

    # Run ID must be fresh, and previous run must be preserved in DB
    assert run1_id != run2_id
    runs = await repository.list_runs()
    run_ids = [r["id"] for r in runs]
    assert run1_id in run_ids
    assert run2_id in run_ids


@pytest.mark.asyncio
async def test_api_simulation_runs_endpoint():
    """Verify GET /api/simulation/runs endpoint returns run history list."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/simulation/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert "runs" in data
        assert isinstance(data["runs"], list)


@pytest.mark.asyncio
async def test_provider_abstraction_contracts():
    """Verify BaseDecisionProvider inheritance and behavior across implementations."""
    rule_provider = RuleBasedProvider()
    assert isinstance(rule_provider, BaseDecisionProvider)
    assert rule_provider.name == "rule_based"
    assert await rule_provider.check_availability() is True

    ollama_provider = OllamaProvider(host="http://localhost:11434", model="qwen2.5:1.5b")
    assert isinstance(ollama_provider, BaseDecisionProvider)
    assert "ollama_" in ollama_provider.name
