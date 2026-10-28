"""
backend/repository.py
─────────────────────
Data access repository implementing persistence queries for runs,
historical telemetry readings, and agent decision audit records.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import desc, select, update

from backend.database import get_db_session
from backend.db_models import DecisionRecordModel, HistoricalReadingModel, SimulationRunModel
from backend.models import AgentDecision, HistoryEntry

logger = logging.getLogger(__name__)


class DatabaseRepository:
    """Async repository for querying and mutating Eco-Loop database records."""

    @staticmethod
    def generate_run_id() -> str:
        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        short_uuid = uuid.uuid4().hex[:6]
        return f"run_{timestamp_str}_{short_uuid}"

    async def create_run(self, baseline_mode: str = "measured") -> str:
        """Create a new active simulation run record and return its run_id."""
        run_id = self.generate_run_id()
        async with get_db_session() as session:
            # Mark any existing active runs as inactive
            await session.execute(
                update(SimulationRunModel)
                .where(SimulationRunModel.is_active.is_(True))
                .values(is_active=False, ended_at=datetime.now(timezone.utc))
            )
            run = SimulationRunModel(
                id=run_id,
                started_at=datetime.now(timezone.utc),
                is_active=True,
                baseline_mode=baseline_mode,
            )
            session.add(run)
        logger.info("Created new database simulation run: %s", run_id)
        return run_id

    async def get_active_run_id(self) -> Optional[str]:
        """Fetch the current active run_id if any exists."""
        async with get_db_session() as session:
            result = await session.execute(
                select(SimulationRunModel.id)
                .where(SimulationRunModel.is_active.is_(True))
                .order_by(desc(SimulationRunModel.started_at))
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def complete_run(
        self,
        run_id: str,
        total_steps: int,
        total_energy: float,
        baseline_energy: float,
        savings_pct: float,
        comfort_score: float,
    ) -> None:
        """Mark a simulation run completed with final summary metrics."""
        async with get_db_session() as session:
            await session.execute(
                update(SimulationRunModel)
                .where(SimulationRunModel.id == run_id)
                .values(
                    is_active=False,
                    ended_at=datetime.now(timezone.utc),
                    total_steps=total_steps,
                    total_energy_kwh=round(total_energy, 3),
                    baseline_energy_kwh=round(baseline_energy, 3),
                    final_savings_pct=round(savings_pct, 2),
                    final_comfort_score=round(comfort_score, 4),
                )
            )
        logger.info("Marked simulation run %s as completed.", run_id)

    async def record_reading(self, run_id: str, entry: HistoryEntry, timestep: int) -> None:
        """Persist a single timestep's telemetry record."""
        async with get_db_session() as session:
            record = HistoricalReadingModel(
                run_id=run_id,
                timestep=timestep,
                sim_time=entry.sim_time,
                wall_time=entry.wall_time,
                avg_temp=entry.avg_temp,
                hvac_power_kw=entry.hvac_power_kw,
                total_energy_kwh=entry.total_energy_kwh,
                comfort_score=entry.comfort_score,
                energy_savings_pct=entry.energy_savings_pct,
                outdoor_temp=entry.outdoor_temp,
                occupancy=entry.occupancy,
                ai_energy_mode=entry.ai_energy_mode,
            )
            session.add(record)

    async def record_decision(
        self,
        run_id: str,
        decision: AgentDecision,
        timestep: int,
        actuation_status: str = "applied",
    ) -> None:
        """Persist an agent decision record for auditability with verified actuation status."""
        setpoints_dict = {
            zone: {"cooling": sp.cooling, "heating": sp.heating}
            for zone, sp in decision.zone_setpoints.items()
        }
        async with get_db_session() as session:
            record = DecisionRecordModel(
                run_id=run_id,
                timestamp=datetime.now(timezone.utc),
                timestep=timestep,
                controller_source=decision.controller_source,
                energy_mode=decision.energy_mode,
                fan_speed=decision.fan_speed,
                confidence=decision.confidence,
                estimated_savings_pct=decision.estimated_savings_pct,
                reasoning=decision.reasoning,
                actuation_status=actuation_status,
                zone_setpoints_json=json.dumps(setpoints_dict),
            )
            session.add(record)

    async def get_history(self, run_id: Optional[str] = None, limit: int = 100) -> List[HistoryEntry]:
        """Fetch historical readings ordered chronologically."""
        async with get_db_session() as session:
            stmt = select(HistoricalReadingModel)
            if run_id:
                stmt = stmt.where(HistoricalReadingModel.run_id == run_id)
            stmt = stmt.order_by(desc(HistoricalReadingModel.id)).limit(limit)
            result = await session.execute(stmt)
            rows = result.scalars().all()

        # Reverse to chronological order
        return [
            HistoryEntry(
                sim_time=r.sim_time,
                wall_time=r.wall_time,
                avg_temp=r.avg_temp,
                hvac_power_kw=r.hvac_power_kw,
                total_energy_kwh=r.total_energy_kwh,
                comfort_score=r.comfort_score,
                energy_savings_pct=r.energy_savings_pct,
                outdoor_temp=r.outdoor_temp,
                occupancy=r.occupancy,
                ai_energy_mode=r.ai_energy_mode,
            )
            for r in reversed(rows)
        ]

    async def list_runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        """List past simulation runs and summary statistics."""
        async with get_db_session() as session:
            stmt = select(SimulationRunModel).order_by(desc(SimulationRunModel.started_at)).limit(limit)
            result = await session.execute(stmt)
            runs = result.scalars().all()

        return [
            {
                "id": r.id,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "ended_at": r.ended_at.isoformat() if r.ended_at else None,
                "is_active": r.is_active,
                "baseline_mode": r.baseline_mode,
                "total_steps": r.total_steps,
                "total_energy_kwh": r.total_energy_kwh,
                "baseline_energy_kwh": r.baseline_energy_kwh,
                "final_savings_pct": r.final_savings_pct,
                "final_comfort_score": r.final_comfort_score,
            }
            for r in runs
        ]


repository = DatabaseRepository()
