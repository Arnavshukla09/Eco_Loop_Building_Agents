"""
backend/state.py
────────────────
Thread-safe, in-process shared state store.

All components (simulation runner, AI agent, MCP server, WebSocket broadcaster)
read and write through this singleton so there is exactly one source of truth.
"""
from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional

from backend.models import (
    AgentDecision,
    BuildingObservation,
    DashboardUpdate,
    HistoryEntry,
    MetricsSummary,
    ZoneSetpoint,
    ZoneState,
)
from config.settings import settings

# ── CO₂ intensity (kg CO₂ per kWh) — US average grid ────────────────────────
CO2_KG_PER_KWH = 0.386


class BuildingStateStore:
    """
    Central in-memory state store.

    Uses a reentrant thread lock for synchronous access and an asyncio event
    to notify waiting coroutines of state updates without polling.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._async_event: Optional[asyncio.Event] = None

        # Current state
        self._observation: Optional[BuildingObservation] = None
        self._decision: Optional[AgentDecision] = None
        self._simulation_running: bool = False
        self._llm_available: bool = False
        self._mcp_running: bool = False
        self._simulation_mode: bool = settings.SIMULATION_MODE
        self._start_time: float = time.monotonic()

        # Baseline tracking (energy that WOULD have been used without AI)
        self._baseline_energy_kwh: float = 0.0
        self._peak_demand_kw: float = 0.0

        # History ring-buffer
        self._history: Deque[HistoryEntry] = deque(maxlen=settings.HISTORY_MAX_LEN)

    # ── Async event (lazy-initialised inside event loop) ─────────────────────

    def _get_event(self) -> asyncio.Event:
        if self._async_event is None:
            self._async_event = asyncio.Event()
        return self._async_event

    def _notify(self) -> None:
        """Signal waiting coroutines that state has been updated."""
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(self._get_event().set)
        except RuntimeError:
            pass  # No running loop (called from sync context during startup)

    async def wait_for_update(self, timeout: float = 5.0) -> bool:
        """Await until the state changes or timeout (seconds) is reached."""
        event = self._get_event()
        event.clear()
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    # ── Observation updates ──────────────────────────────────────────────────

    def update_observation(self, obs: BuildingObservation) -> None:
        with self._lock:
            self._observation = obs
            # Track peak demand
            if obs.hvac_power_kw > self._peak_demand_kw:
                self._peak_demand_kw = obs.hvac_power_kw
            # Append compact history entry
            metrics = self._compute_metrics_locked(obs)
            entry = HistoryEntry(
                sim_time=obs.simulation_time,
                wall_time=obs.timestamp,
                avg_temp=obs.avg_temperature,
                hvac_power_kw=obs.hvac_power_kw,
                total_energy_kwh=obs.total_energy_kwh,
                comfort_score=metrics.comfort_score,
                energy_savings_pct=metrics.energy_savings_pct,
                outdoor_temp=obs.outdoor_temp,
                occupancy=obs.occupancy,
                ai_energy_mode=self._decision.energy_mode if self._decision else None,
            )
            self._history.append(entry)
        self._notify()

    def update_baseline_energy(self, baseline_kwh: float) -> None:
        with self._lock:
            self._baseline_energy_kwh = baseline_kwh

    # ── Decision updates ─────────────────────────────────────────────────────

    def update_decision(self, decision: AgentDecision) -> None:
        with self._lock:
            self._decision = decision
        self._notify()

    # ── Status flags ─────────────────────────────────────────────────────────

    def set_simulation_running(self, running: bool) -> None:
        with self._lock:
            self._simulation_running = running

    def set_llm_available(self, available: bool) -> None:
        with self._lock:
            self._llm_available = available

    def set_mcp_running(self, running: bool) -> None:
        with self._lock:
            self._mcp_running = running

    # ── Getters ──────────────────────────────────────────────────────────────

    def get_observation(self) -> Optional[BuildingObservation]:
        with self._lock:
            return self._observation

    def get_decision(self) -> Optional[AgentDecision]:
        with self._lock:
            return self._decision

    def get_history(self, limit: int = 100) -> List[HistoryEntry]:
        with self._lock:
            entries = list(self._history)
        return entries[-limit:]

    # ── State Mutation Helpers ───────────────────────────────────────────────

    def update_setpoint(self, zone: str, cooling: float, heating: float) -> None:
        """Immediately update setpoints on the cached observation if present."""
        with self._lock:
            if self._observation is not None and zone in self._observation.zones:
                z = self._observation.zones[zone]
                self._observation.zones[zone] = z.model_copy(
                    update={"setpoint_cooling": cooling, "setpoint_heating": heating}
                )
        self._notify()

    def reset(self) -> None:
        """Clear historical ring-buffer and accumulated energy metrics."""
        with self._lock:
            self._history.clear()
            self._baseline_energy_kwh = 0.0
            self._peak_demand_kw = 0.0
            self._decision = None
        self._notify()

    def is_simulation_running(self) -> bool:
        with self._lock:
            return self._simulation_running

    def is_llm_available(self) -> bool:
        with self._lock:
            return self._llm_available

    def is_mcp_running(self) -> bool:
        with self._lock:
            return self._mcp_running

    def get_uptime(self) -> float:
        return time.monotonic() - self._start_time

    # ── Metrics computation ──────────────────────────────────────────────────

    def _compute_metrics_locked(self, obs: BuildingObservation) -> MetricsSummary:
        """Compute KPI metrics from real measurements. Must be called with lock held."""
        # Comfort: map avg PPD to [0, 1] score (100% PPD → 0, 5% PPD → 1)
        avg_ppd = obs.avg_ppd
        comfort_score = max(0.0, 1.0 - avg_ppd / 100.0)

        # Baseline energy: use measured fixed-setpoint reference if available
        if self._baseline_energy_kwh > 0.0:
            baseline_kwh = self._baseline_energy_kwh
            baseline_mode = "measured"
            savings_pct = (baseline_kwh - obs.total_energy_kwh) / baseline_kwh * 100.0
            co2_saved = (baseline_kwh - obs.total_energy_kwh) * CO2_KG_PER_KWH
        else:
            # Baseline unmeasured or same as current at step 0
            baseline_kwh = obs.total_energy_kwh
            baseline_mode = "unmeasured"
            savings_pct = 0.0
            co2_saved = 0.0

        return MetricsSummary(
            comfort_score=round(comfort_score, 4),
            energy_savings_pct=round(savings_pct, 2),
            baseline_energy_kwh=round(baseline_kwh, 3),
            current_energy_kwh=round(obs.total_energy_kwh, 3),
            co2_saved_kg=round(co2_saved, 3),
            peak_demand_kw=round(self._peak_demand_kw, 2),
            avg_temp_c=round(obs.avg_temperature, 2),
            baseline_mode=baseline_mode,
        )

    def get_metrics(self) -> Optional[MetricsSummary]:
        with self._lock:
            if self._observation is None:
                return None
            return self._compute_metrics_locked(self._observation)

    def get_dashboard_update(self) -> Optional[DashboardUpdate]:
        with self._lock:
            obs = self._observation
            if obs is None:
                return None
            metrics = self._compute_metrics_locked(obs)
            return DashboardUpdate(
                timestamp=datetime.now(timezone.utc),
                building=obs,
                ai_decision=self._decision,
                metrics=metrics,
                simulation_mode=self._simulation_mode,
            )

    # ── Setpoint convenience helper ──────────────────────────────────────────

    def get_current_setpoints(self) -> Dict[str, ZoneSetpoint]:
        """Return current setpoints keyed by zone name."""
        with self._lock:
            obs = self._observation
        if obs is None:
            return {
                z: ZoneSetpoint(
                    cooling=settings.COOLING_SETPOINT_DEFAULT,
                    heating=settings.HEATING_SETPOINT_DEFAULT,
                )
                for z in settings.ZONES
            }
        return {
            name: ZoneSetpoint(
                cooling=zone.setpoint_cooling,
                heating=zone.setpoint_heating,
            )
            for name, zone in obs.zones.items()
        }


# ── Module-level singleton ────────────────────────────────────────────────────
state_store = BuildingStateStore()
