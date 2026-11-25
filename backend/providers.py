"""
backend/providers.py
────────────────────
Pluggable supervisory decision provider abstraction.
Decouples LLM inference from domain logic and provides formal interfaces
for local LLMs (Ollama) and deterministic fallback controllers.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
import json
import logging
import time
from typing import Dict, List, Optional

from backend.models import AgentDecision, BuildingObservation, HistoryEntry, ZoneSetpoint
from config.settings import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are the Honeywell Eco-Loop Building Automation AI Agent.
Your job is to optimize HVAC thermostat setpoints and fan speed for commercial buildings.
You must balance energy efficiency with occupant thermal comfort.
Rules:
1. Cooling setpoint must be between 20.0°C and 30.0°C.
2. Heating setpoint must be between 16.0°C and 22.0°C.
3. Cooling setpoint must be >= heating setpoint + 1.5°C at all times.
4. Output valid JSON matching the schema strictly.
"""


class BaseDecisionProvider(ABC):
    """Abstract interface for all HVAC supervisory decision engines."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier."""
        ...

    @abstractmethod
    async def decide(
        self,
        obs: BuildingObservation,
        history: Optional[List[HistoryEntry]] = None,
    ) -> AgentDecision:
        """Generate supervisory setpoints and fan speed control decision."""
        ...

    @abstractmethod
    async def check_availability(self, force: bool = False) -> bool:
        """Check operational readiness of the provider."""
        ...


class RuleBasedProvider(BaseDecisionProvider):
    """Deterministic rule-based supervisor based on occupancy and outdoor ambient conditions."""

    @property
    def name(self) -> str:
        return "rule_based"

    async def check_availability(self, force: bool = False) -> bool:
        return True

    async def decide(
        self,
        obs: BuildingObservation,
        history: Optional[List[HistoryEntry]] = None,
    ) -> AgentDecision:
        from backend.llm_agent import _rule_based_decision
        return _rule_based_decision(obs)

    async def _legacy_decide(
        self,
        obs: BuildingObservation,
        history: Optional[List[HistoryEntry]] = None,
    ) -> AgentDecision:
        setpoints: Dict[str, ZoneSetpoint] = {}
        outdoor = obs.outdoor_temp
        occupancy = obs.occupancy

        for name, zone in obs.zones.items():
            cool = zone.setpoint_cooling
            heat = zone.setpoint_heating

            # Adjust for outdoor heat
            if outdoor > 28.0:
                cool = min(cool + 0.5, settings.COOLING_SETPOINT_MAX)
            elif outdoor < 0.0:
                heat = max(heat - 0.5, settings.HEATING_SETPOINT_MIN)

            # Widen deadband during low occupancy
            if occupancy < 0.2:
                cool = min(cool + 1.0, settings.COOLING_SETPOINT_MAX)
                heat = max(heat - 1.0, settings.HEATING_SETPOINT_MIN)

            # Tighten for comfort if PMV is far off
            if zone.pmv_score > 1.0:
                cool = max(cool - 0.5, settings.COOLING_SETPOINT_MIN)
            elif zone.pmv_score < -1.0:
                heat = min(heat + 0.5, settings.HEATING_SETPOINT_MAX)

            if cool < heat + 1.5:
                cool = min(settings.COOLING_SETPOINT_MAX, heat + 1.5)
                heat = max(settings.HEATING_SETPOINT_MIN, cool - 1.5)

            setpoints[name] = ZoneSetpoint(cooling=round(cool, 1), heating=round(heat, 1))

        energy_mode = "eco" if occupancy < 0.2 else ("comfort" if occupancy > 0.8 else "balanced")
        fan_speed = "low" if occupancy < 0.2 else ("high" if occupancy > 0.8 else "medium")

        return AgentDecision(
            zone_setpoints=setpoints,
            fan_speed=fan_speed,
            energy_mode=energy_mode,
            controller_source="rule_based",
            reasoning=(
                f"[Rule-based] Occupancy {occupancy * 100:.0f}%, outdoor {outdoor:.1f}°C. "
                f"Mode: {energy_mode}. Setpoints balanced for efficiency."
            ),
            confidence=0.85,
            estimated_savings_pct=8.0 if energy_mode == "eco" else 4.0,
        )


class ScheduledProvider(BaseDecisionProvider):
    """Conventional occupied/unoccupied schedule used as a competitive baseline."""
    @property
    def name(self):
        return "scheduled"

    async def check_availability(self, force=False):
        return True

    async def decide(self, obs, history=None):
        occupied = obs.occupancy >= 0.2
        cool, heat = (24.0, 20.5) if occupied else (28.0, 17.0)
        return AgentDecision(controller_source=self.name, zone_setpoints={z: ZoneSetpoint(cooling=cool, heating=heat) for z in obs.zones}, fan_speed="medium" if occupied else "low", energy_mode="balanced" if occupied else "eco", reasoning="Scheduled occupied comfort band and unoccupied setback.", confidence=1.0)


class ForecastProvider(ScheduledProvider):
    """Explicit heuristic supervisor using expected occupancy, weather, and tariff."""
    @property
    def name(self):
        return "forecast"

    async def decide(self, obs, history=None):
        decision = await super().decide(obs, history)
        soon = obs.forecast[:2]
        preoccupancy = obs.occupancy < 0.2 and any(p["occupancy"] >= 0.2 for p in soon)
        expensive = obs.electricity_rate >= settings.TARIFF_PEAK and settings.TARIFF_PEAK > settings.TARIFF_OFFPEAK
        hot_soon = any(p["outdoor_temp"] > 25 and p["electricity_rate"] > obs.electricity_rate for p in soon)
        for name, sp in decision.zone_setpoints.items():
            if preoccupancy:
                sp.cooling, sp.heating = 24.0, 20.5
            if obs.occupancy >= 0.2 and expensive:
                sp.cooling += 0.5
                sp.heating -= 0.5
            elif obs.occupancy >= 0.2 and hot_soon:
                sp.cooling -= 0.5
            pmv = obs.zones[name].pmv_score
            if obs.occupancy >= 0.2 and pmv > 0.5:
                sp.cooling = max(22.0, sp.cooling - 0.5)
            elif obs.occupancy >= 0.2 and pmv < -0.5:
                sp.heating = min(22.0, sp.heating + 0.5)
        decision.controller_source = self.name
        decision.reasoning = f"Forecast heuristic: preoccupancy={preoccupancy}, peak tariff={expensive}, hot period ahead={hot_soon}. Occupied PMV corrections take priority."
        return decision


class OllamaProvider(BaseDecisionProvider):
    """Local LLM provider calling Ollama with structured schema outputs and verified model check."""

    def __init__(self, host: str, model: str, temperature: float = 0.1, timeout: int = 60) -> None:
        self.host = host
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self._available = False
        self._last_check_time: float = 0.0

    @property
    def name(self) -> str:
        return f"ollama_{self.model}"

    async def check_availability(self, force: bool = False) -> bool:
        now = time.monotonic()
        if not force and (now - self._last_check_time < 30.0):
            return self._available
        self._last_check_time = now

        try:
            import ollama
            client = ollama.AsyncClient(host=self.host)
            models = await asyncio.wait_for(client.list(), timeout=3.0)
            avail = [m.model for m in models.models] if hasattr(models, "models") else []
            has_model = (self.model if ":" in self.model else self.model + ":latest") in avail
            self._available = has_model
            return has_model
        except Exception:
            self._available = False
            return False

    async def decide(
        self,
        obs: BuildingObservation,
        history: Optional[List[HistoryEntry]] = None,
    ) -> AgentDecision:
        if not self._available and not await self.check_availability():
            raise RuntimeError(f"Ollama provider '{self.model}' is currently unavailable.")

        import ollama
        client = ollama.AsyncClient(host=self.host)

        recent_hist = history[-10:] if history else []
        context = {
            "simulation_time": obs.simulation_time.isoformat(),
            "outdoor_temp": obs.outdoor_temp,
            "outdoor_humidity": obs.outdoor_humidity,
            "occupancy": obs.occupancy,
            "total_energy_kwh": obs.total_energy_kwh,
            "hvac_power_kw": obs.hvac_power_kw,
            "zones": {
                name: {
                    "temp": z.temperature,
                    "cooling_sp": z.setpoint_cooling,
                    "heating_sp": z.setpoint_heating,
                    "pmv": z.pmv_score,
                    "ppd": z.ppd_score,
                }
                for name, z in obs.zones.items()
            },
            "recent_readings_count": len(recent_hist),
            "forecast": obs.forecast,
            "electricity_rate": obs.electricity_rate,
        }

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(context)},
        ]

        response = await asyncio.wait_for(
            client.chat(
                model=self.model,
                messages=messages,
                format=AgentDecision.model_json_schema(),
                options={"temperature": self.temperature, "num_predict": 600, "top_p": 0.9},
            ),
            timeout=float(self.timeout),
        )

        decision = AgentDecision.model_validate_json(response.message.content)
        decision.controller_source = "llm"
        return decision
