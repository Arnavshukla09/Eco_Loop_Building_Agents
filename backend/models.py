"""
backend/models.py
─────────────────
All shared Pydantic data models.
These are the single source of truth for data shapes across:
  - EnergyPlus runner output
  - LLM agent input / output
  - MCP server tool responses
  - WebSocket / REST API payloads
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, computed_field, model_validator

# ── Zone-level state ──────────────────────────────────────────────────────────

class ZoneState(BaseModel):
    """Thermal and comfort state of a single HVAC zone."""

    zone_id: str
    temperature: float = Field(..., description="Current mean air temperature (°C)")
    setpoint_cooling: float = Field(..., description="Active cooling setpoint (°C)")
    setpoint_heating: float = Field(..., description="Active heating setpoint (°C)")
    pmv_score: float = Field(..., description="Predicted Mean Vote (-3 … +3, 0 = neutral)")
    ppd_score: float = Field(..., description="Predicted Percentage Dissatisfied (0–100 %)")
    humidity: float = Field(..., description="Relative humidity (%)")

    @computed_field
    @property
    def comfort_label(self) -> str:
        if abs(self.pmv_score) < 0.5:
            return "Comfortable"
        if abs(self.pmv_score) < 1.0:
            return "Slightly Uncomfortable"
        return "Uncomfortable"


# ── Building-level observation ────────────────────────────────────────────────

class BuildingObservation(BaseModel):
    """Full snapshot of building state at one simulation timestep."""

    timestamp: datetime = Field(description="Wall-clock time of this observation")
    simulation_time: datetime = Field(description="Simulated building time")
    zones: Dict[str, ZoneState]
    outdoor_temp: float = Field(..., description="Outdoor dry-bulb temperature (°C)")
    outdoor_humidity: float = Field(..., description="Outdoor relative humidity (%)")
    total_energy_kwh: float = Field(..., description="Cumulative HVAC energy consumed (kWh)")
    hvac_power_kw: float = Field(..., description="Instantaneous HVAC power draw (kW)")
    occupancy: float = Field(..., ge=0.0, le=1.0, description="Building occupancy ratio (0–1)")
    timestep: int = Field(default=0, description="Sequential timestep counter")

    @computed_field
    @property
    def avg_temperature(self) -> float:
        if not self.zones:
            return 0.0
        return sum(z.temperature for z in self.zones.values()) / len(self.zones)

    @computed_field
    @property
    def avg_pmv(self) -> float:
        if not self.zones:
            return 0.0
        return sum(z.pmv_score for z in self.zones.values()) / len(self.zones)

    @computed_field
    @property
    def avg_ppd(self) -> float:
        if not self.zones:
            return 0.0
        return sum(z.ppd_score for z in self.zones.values()) / len(self.zones)


# ── AI agent decision ─────────────────────────────────────────────────────────

class ZoneSetpoint(BaseModel):
    """Heating / cooling setpoint pair for one zone."""

    cooling: float = Field(..., ge=18.0, le=32.0, description="Cooling setpoint (°C)")
    heating: float = Field(..., ge=10.0, le=25.0, description="Heating setpoint (°C)")

    @model_validator(mode="after")
    def validate_deadband(self) -> "ZoneSetpoint":
        if self.cooling <= self.heating:
            raise ValueError(f"Cooling setpoint ({self.cooling}°C) must be above heating setpoint ({self.heating}°C)")
        return self


class AgentDecision(BaseModel):
    """Structured decision returned by the AI agent for each control cycle."""

    controller_source: str = Field(
        default="rule_based",
        description="Active controller: 'llm' (verified inference) or 'rule_based' (deterministic fallback)",
    )
    zone_setpoints: Dict[str, ZoneSetpoint] = Field(
        description="Recommended heating/cooling setpoints per zone."
    )
    fan_speed: str = Field(
        default="medium",
        pattern="^(low|medium|high)$",
        description="Recommended fan speed.",
    )
    energy_mode: str = Field(
        default="balanced",
        pattern="^(eco|balanced|comfort)$",
        description="Overall HVAC operating mode.",
    )
    reasoning: str = Field(
        description="Plain-English explanation of the decision (≤ 200 words)."
    )
    confidence: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Agent confidence in this decision (0–1).",
    )
    estimated_savings_pct: float = Field(
        default=0.0,
        description="Estimated energy saving versus baseline (%).",
    )


# ── Metrics summary ───────────────────────────────────────────────────────────

class MetricsSummary(BaseModel):
    """Rolled-up KPIs shown on the dashboard header cards."""

    comfort_score: float = Field(
        ..., ge=0.0, le=1.0, description="Normalised comfort index (1 = perfect)."
    )
    energy_savings_pct: float = Field(
        ..., description="Cumulative energy savings vs baseline (%)."
    )
    baseline_energy_kwh: float = Field(
        ..., description="Baseline energy usage (kWh)."
    )
    current_energy_kwh: float = Field(..., description="Actual cumulative energy (kWh).")
    co2_saved_kg: float = Field(..., description="Estimated CO₂ avoided (kg).")
    peak_demand_kw: float = Field(default=0.0)
    avg_temp_c: float = Field(default=21.0)
    baseline_mode: str = Field(
        default="measured",
        description="Whether baseline is 'measured' via fixed setpoint reference or 'estimated'.",
    )


# ── WebSocket / API payloads ──────────────────────────────────────────────────

class DashboardUpdate(BaseModel):
    """Full state broadcast sent over WebSocket to the dashboard."""

    type: str = "state_update"
    timestamp: datetime
    building: BuildingObservation
    ai_decision: Optional[AgentDecision] = None
    metrics: MetricsSummary
    simulation_mode: bool = True


class HistoryEntry(BaseModel):
    """Compact record stored in the history buffer."""

    sim_time: datetime
    wall_time: datetime
    avg_temp: float
    hvac_power_kw: float
    total_energy_kwh: float
    comfort_score: float
    energy_savings_pct: float
    outdoor_temp: float
    occupancy: float
    ai_energy_mode: Optional[str] = None


# ── Setpoint Validation & Command ─────────────────────────────────────────────

def validate_setpoints(cooling: float, heating: float, zone: Optional[str] = None) -> None:
    """
    Canonical setpoint validation across REST API, MCP tools, and autonomous control.
    Enforces physical safety limits and ASHRAE minimum 1.5°C deadband.
    Raises ValueError on validation failure.
    """
    from config.settings import settings

    if zone is not None and zone not in settings.ZONES:
        raise ValueError(f"Unknown zone '{zone}'. Valid zones: {settings.ZONES}")

    if cooling < settings.COOLING_SETPOINT_MIN or cooling > settings.COOLING_SETPOINT_MAX:
        raise ValueError(
            f"Cooling setpoint {cooling:.1f}°C is outside valid range "
            f"[{settings.COOLING_SETPOINT_MIN:.1f}°C, {settings.COOLING_SETPOINT_MAX:.1f}°C]."
        )

    if heating < settings.HEATING_SETPOINT_MIN or heating > settings.HEATING_SETPOINT_MAX:
        raise ValueError(
            f"Heating setpoint {heating:.1f}°C is outside valid range "
            f"[{settings.HEATING_SETPOINT_MIN:.1f}°C, {settings.HEATING_SETPOINT_MAX:.1f}°C]."
        )

    deadband = cooling - heating
    if deadband < 1.5:
        raise ValueError(
            f"Deadband constraint violated: cooling ({cooling:.1f}°C) must exceed "
            f"heating ({heating:.1f}°C) by at least 1.5°C (current gap: {deadband:.1f}°C)."
        )


class SetpointCommand(BaseModel):
    """Manual setpoint override via REST API."""

    zone: Optional[str] = Field(
        default=None,
        description="Zone to update (None = apply to all zones).",
    )
    cooling: float = Field(..., description="Cooling setpoint (°C)")
    heating: float = Field(..., description="Heating setpoint (°C)")

    @model_validator(mode="after")
    def validate_canonical_limits(self) -> "SetpointCommand":
        validate_setpoints(self.cooling, self.heating, self.zone)
        return self


class HealthStatus(BaseModel):
    status: str = "ok"  # "ok", "degraded", "starting"
    liveness: bool = True
    readiness: bool = False
    simulation_running: bool
    llm_available: bool
    mcp_running: bool
    controller_mode: str = "rule_based"  # "llm" or "rule_based"
    uptime_seconds: float
    simulation_mode: bool
    model: str
    timestep: int
