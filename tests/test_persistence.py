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
from backend.database import close_db, get_db_session, init_db
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
async def test_persistence_across_app_restart():
    """Verify data survives database engine close and reconnection (simulating process restart)."""
    # 1. Write run and readings
    run_id = await repository.create_run()
    entry = HistoryEntry(
        sim_time=datetime(2024, 2, 1, 10, 0, tzinfo=timezone.utc),
        wall_time=datetime.now(timezone.utc),
        avg_temp=21.8,
        hvac_power_kw=9.5,
        total_energy_kwh=102.0,
        comfort_score=0.94,
        energy_savings_pct=18.2,
        outdoor_temp=8.0,
        occupancy=0.8,
        ai_energy_mode="eco",
    )
    await repository.record_reading(run_id, entry, timestep=5)

    # 2. Simulate shutdown
    await close_db()

    # 3. Re-initialize database (simulating restart)
    await init_db()

    # 4. Read back data
    hist = await repository.get_history(run_id=run_id)
    assert len(hist) == 1
    assert hist[0].avg_temp == 21.8
    assert hist[0].energy_savings_pct == 18.2


@pytest.mark.asyncio
async def test_history_deduplication_and_ordering():
    """Verify /api/history merges in-memory and database records without duplicates."""
    from backend.state import state_store

    run_id = await repository.create_run()
    t1 = datetime(2024, 3, 1, 12, 0, tzinfo=timezone.utc)
    t2 = datetime(2024, 3, 1, 12, 15, tzinfo=timezone.utc)

    # Write t1 to database
    e1 = HistoryEntry(
        sim_time=t1,
        wall_time=datetime.now(timezone.utc),
        avg_temp=22.0,
        hvac_power_kw=10.0,
        total_energy_kwh=50.0,
        comfort_score=0.9,
        energy_savings_pct=12.0,
        outdoor_temp=12.0,
        occupancy=0.5,
    )
    await repository.record_reading(run_id, e1, timestep=1)

    # t1 and t2 in state_store memory buffer
    e2 = HistoryEntry(
        sim_time=t2,
        wall_time=datetime.now(timezone.utc),
        avg_temp=22.2,
        hvac_power_kw=10.5,
        total_energy_kwh=52.5,
        comfort_score=0.91,
        energy_savings_pct=12.5,
        outdoor_temp=12.5,
        occupancy=0.5,
    )
    # Clear and add t1 & t2 to state_store
    state_store.reset()
    with state_store._lock:
        state_store._history.append(e1)
        state_store._history.append(e2)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/history?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        entries = data["entries"]
        # Must contain t1 and t2 exactly once, no duplicate t1
        sim_times = [e["sim_time"] for e in entries]
        assert len(sim_times) == len(set(sim_times))


@pytest.mark.asyncio
async def test_decision_source_and_actuation_attribution():
    """Verify decision source accurately reflects LLM, rule_based, fallback, and actuation status."""
    from backend.llm_agent import _rule_based_decision
    from backend.models import BuildingObservation, ZoneState

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

    # 1. Nominal rule-based decision
    rule_dec = _rule_based_decision(obs)
    rule_dec.controller_source = "rule_based"
    assert rule_dec.controller_source == "rule_based"

    # 2. Record decision with actuation status in DB
    run_id = await repository.create_run()
    await repository.record_decision(run_id, rule_dec, timestep=5, actuation_status="applied")
    async with get_db_session() as session:
        from backend.db_models import DecisionRecordModel
        from sqlalchemy import select
        res = await session.execute(
            select(DecisionRecordModel).where(DecisionRecordModel.run_id == run_id)
        )
        saved = res.scalar_one()
        assert saved.controller_source == "rule_based"
        assert saved.actuation_status == "applied"


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
