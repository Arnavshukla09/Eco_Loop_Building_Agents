"""
backend/db_models.py
────────────────────
SQLAlchemy Declarative Models for Eco-Loop Building Automation.
Persists simulation runs, historical sensor telemetry, and AI decisions.
"""
from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from backend.database import Base


class SimulationRunModel(Base):
    """Represents a discrete simulation session / run (persisting across resets)."""

    __tablename__ = "simulation_runs"

    id = Column(String(64), primary_key=True, index=True)
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    baseline_mode = Column(String(32), default="measured", nullable=False)
    total_steps = Column(Integer, default=0, nullable=False)
    total_energy_kwh = Column(Float, default=0.0, nullable=False)
    baseline_energy_kwh = Column(Float, default=0.0, nullable=False)
    final_savings_pct = Column(Float, default=0.0, nullable=False)
    final_comfort_score = Column(Float, default=0.0, nullable=False)

    readings = relationship("HistoricalReadingModel", back_populates="run", cascade="all, delete-orphan")
    decisions = relationship("DecisionRecordModel", back_populates="run", cascade="all, delete-orphan")


class HistoricalReadingModel(Base):
    """Historical telemetry record at each simulation timestep."""

    __tablename__ = "historical_readings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    timestep = Column(Integer, nullable=False, index=True)
    sim_time = Column(DateTime(timezone=True), nullable=False)
    wall_time = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    avg_temp = Column(Float, nullable=False)
    hvac_power_kw = Column(Float, nullable=False)
    total_energy_kwh = Column(Float, nullable=False)
    comfort_score = Column(Float, nullable=False)
    energy_savings_pct = Column(Float, nullable=False)
    outdoor_temp = Column(Float, nullable=False)
    occupancy = Column(Float, nullable=False)
    ai_energy_mode = Column(String(32), nullable=True)

    run = relationship("SimulationRunModel", back_populates="readings")


class DecisionRecordModel(Base):
    """Audit log of AI / rule-based supervisory control decisions."""

    __tablename__ = "decision_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    timestep = Column(Integer, nullable=False)
    controller_source = Column(String(32), nullable=False, index=True)  # "llm" or "rule_based"
    energy_mode = Column(String(32), nullable=False)
    fan_speed = Column(String(32), nullable=False)
    confidence = Column(Float, nullable=False)
    estimated_savings_pct = Column(Float, nullable=False)
    reasoning = Column(Text, nullable=False)
    actuation_status = Column(String(32), default="applied", nullable=False)
    zone_setpoints_json = Column(Text, nullable=False)

    run = relationship("SimulationRunModel", back_populates="decisions")
