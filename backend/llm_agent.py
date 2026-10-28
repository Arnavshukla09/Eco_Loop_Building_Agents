"""
backend/llm_agent.py
─────────────────────
AI Building Agent powered by Qwen2.5 (or Llama3) via Ollama.

Behaviour
─────────
• Connects to a local Ollama server at startup.
• Formats the current BuildingObservation into a structured prompt.
• Requests a JSON response conforming to AgentDecision schema.
• Uses structured output (format= parameter) so the model MUST return valid JSON.
• Falls back to a deterministic rule-based controller if Ollama is unavailable
  or returns invalid JSON, so the system never stops working.

Prompt strategy
───────────────
System prompt: expert building automation engineer with energy optimisation goals.
User message:  current building snapshot as a concise table.
Response format: AgentDecision JSON schema (Pydantic → JSON Schema).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Dict, List, Optional

from backend.models import AgentDecision, BuildingObservation, HistoryEntry, ZoneSetpoint
from config.settings import settings

logger = logging.getLogger(__name__)

# ── System prompt ─────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are EcoLoop AI, an expert building automation engineer specialising in HVAC \
optimisation for smart buildings.

Your goal is to minimise energy consumption while maintaining occupant thermal comfort \
(PMV between -0.5 and +0.5, PPD < 10%).

Rules:
1. Cooling setpoints must be between {cool_min}°C and {cool_max}°C.
2. Heating setpoints must be between {heat_min}°C and {heat_max}°C.
3. Cooling setpoint must always be at least 2°C above the heating setpoint.
4. During low-occupancy hours (< 20%) widen the deadband to save energy.
5. Avoid drastic setpoint changes (> 2°C per cycle) to prevent thermal shock.
6. In summer (outdoor temp > 25°C), prefer raising cooling setpoints to reduce load.
7. In winter (outdoor temp < 5°C), prefer lowering heating setpoints to reduce load.
8. Return ONLY the JSON object — no markdown, no explanation outside the JSON.

Output the AgentDecision JSON schema exactly. The "reasoning" field should be \
a concise 1–3 sentence explanation of your decision.
""".format(
    cool_min=settings.COOLING_SETPOINT_MIN,
    cool_max=settings.COOLING_SETPOINT_MAX,
    heat_min=settings.HEATING_SETPOINT_MIN,
    heat_max=settings.HEATING_SETPOINT_MAX,
)


def _format_observation(obs: BuildingObservation, history: List[HistoryEntry]) -> str:
    """Format building state as a human-readable context string for the LLM."""
    lines = [
        f"=== Building Snapshot (Sim Time: {obs.simulation_time.strftime('%Y-%m-%d %H:%M')}) ===",
        f"Outdoor: {obs.outdoor_temp:.1f}°C | Humidity: {obs.outdoor_humidity:.0f}% | Occupancy: {obs.occupancy * 100:.0f}%",
        f"Cumulative Energy: {obs.total_energy_kwh:.1f} kWh | HVAC Power: {obs.hvac_power_kw:.1f} kW",
        "",
        "Zone Status:",
        f"{'Zone':<15} {'Temp (°C)':<12} {'Cool SP':<10} {'Heat SP':<10} {'PMV':<8} {'PPD %':<8} {'Humidity %'}",
        "-" * 75,
    ]
    for name, zone in obs.zones.items():
        lines.append(
            f"{name:<15} {zone.temperature:<12.1f} {zone.setpoint_cooling:<10.1f} "
            f"{zone.setpoint_heating:<10.1f} {zone.pmv_score:<8.2f} {zone.ppd_score:<8.1f} {zone.humidity:.0f}"
        )

    if history:
        last = history[-1]
        lines += [
            "",
            f"Recent Trend (last {len(history)} steps): avg_temp={last.avg_temp:.1f}°C, "
            f"savings={last.energy_savings_pct:.1f}%",
        ]

    return "\n".join(lines)


# ── Rule-based fallback ───────────────────────────────────────────────────────

def _rule_based_decision(obs: BuildingObservation) -> AgentDecision:
    """
    Deterministic rule-based controller.
    Used when Ollama is unavailable or returns invalid JSON.
    """
    setpoints: Dict[str, ZoneSetpoint] = {}
    outdoor = obs.outdoor_temp
    occupancy = obs.occupancy

    for name, zone in obs.zones.items():
        # Start with current setpoints
        cool = zone.setpoint_cooling
        heat = zone.setpoint_heating

        # Adjust for outdoor temp
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

        # Maintain gap
        if cool <= heat + 1.5:
            cool = heat + 2.0

        setpoints[name] = ZoneSetpoint(cooling=round(cool, 1), heating=round(heat, 1))

    energy_mode = "eco" if occupancy < 0.2 else ("comfort" if occupancy > 0.8 else "balanced")
    fan_speed   = "low" if occupancy < 0.2 else ("high" if occupancy > 0.8 else "medium")

    return AgentDecision(
        zone_setpoints=setpoints,
        fan_speed=fan_speed,
        energy_mode=energy_mode,
        reasoning=(
            f"Rule-based control: occupancy {occupancy * 100:.0f}%, "
            f"outdoor {outdoor:.1f}°C. "
            f"Mode: {energy_mode}. Setpoints adjusted for efficiency and comfort."
        ),
        confidence=0.70,
        estimated_savings_pct=max(0.0, (1.0 - occupancy) * 12.0),
    )


# ── Agent class ───────────────────────────────────────────────────────────────

class BuildingAIAgent:
    """
    AI agent that queries a local Ollama LLM asynchronously and returns structured HVAC decisions.
    """

    def __init__(self) -> None:
        self._model   = settings.LLM_MODEL
        self._host    = settings.OLLAMA_HOST
        self._temp    = settings.LLM_TEMPERATURE
        self._timeout = settings.LLM_TIMEOUT_SECONDS
        self._available = False
        self._last_decision_time: Optional[float] = None
        self._decision_count = 0
        self._last_health_check_time: float = 0.0

        self._initialise_client()

    def _initialise_client(self) -> None:
        try:
            import ollama  # type: ignore
            client = ollama.Client(host=self._host)
            models = client.list()
            available_models = [m.model for m in models.models] if hasattr(models, "models") else []
            if not any(self._model in m for m in available_models):
                logger.warning(
                    "Model '%s' not found in Ollama (available: %s). Run: ollama pull %s",
                    self._model,
                    available_models,
                    self._model,
                )
            self._available = True
            logger.info("Ollama connection established at %s. Model: %s.", self._host, self._model)
        except Exception as exc:
            logger.info("Ollama not currently available (%s). Starting in rule-based fallback mode.", exc)
            self._available = False

    @property
    def is_available(self) -> bool:
        return self._available

    async def check_availability(self) -> bool:
        """Periodic bounded health check allowing recovery if Ollama comes online."""
        now = time.monotonic()
        if now - self._last_health_check_time < 30.0:
            return self._available
        self._last_health_check_time = now

        try:
            import ollama  # type: ignore
            client = ollama.AsyncClient(host=self._host)
            await asyncio.wait_for(client.list(), timeout=3.0)
            if not self._available:
                logger.info("Ollama service recovered! Resuming AI agent inference with model '%s'.", self._model)
            self._available = True
            return True
        except Exception:
            if self._available:
                logger.warning("Ollama connection lost. Switching to rule-based fallback.")
            self._available = False
            return False

    async def _call_ollama_async(self, messages: list) -> Optional[str]:
        """Non-blocking call to Ollama with timeout and bounded retry."""
        import ollama  # type: ignore

        client = ollama.AsyncClient(host=self._host)
        last_exc: Optional[Exception] = None

        for attempt in range(1, 3):
            try:
                response = await asyncio.wait_for(
                    client.chat(
                        model=self._model,
                        messages=messages,
                        format=AgentDecision.model_json_schema(),
                        options={
                            "temperature": self._temp,
                            "num_predict": 600,
                            "top_p": 0.9,
                        },
                    ),
                    timeout=float(self._timeout),
                )
                return response.message.content
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError as exc:
                last_exc = exc
                logger.warning("Ollama inference timed out after %ds (attempt %d/2).", self._timeout, attempt)
                if attempt < 2:
                    await asyncio.sleep(1.0)
            except Exception as exc:
                last_exc = exc
                logger.warning("Ollama inference call failed on attempt %d/2: %s", attempt, exc)
                if attempt < 2:
                    await asyncio.sleep(1.0)

        # Retries exhausted
        self._available = False
        logger.warning("Ollama inference unavailable after retries (%s). Using fallback.", last_exc)
        return None

    async def analyze_and_decide(
        self,
        obs: BuildingObservation,
        history: Optional[List[HistoryEntry]] = None,
    ) -> AgentDecision:
        """
        Main entry point. Asynchronously queries Ollama or falls back safely.
        """
        if history is None:
            history = []

        start = time.monotonic()

        # Check for recovery if currently marked unavailable
        if not self._available:
            await self.check_availability()

        if not self._available:
            logger.debug("LLM unavailable – using rule-based fallback.")
            decision = _rule_based_decision(obs)
            decision.reasoning = "[Rule-based] " + decision.reasoning
            return decision

        # Format context
        context = _format_observation(obs, history[-10:])
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": context},
        ]

        try:
            raw = await self._call_ollama_async(messages)
            if raw is None:
                raise ValueError("Empty or failed response from Ollama.")

            decision = AgentDecision.model_validate_json(raw)
            # Validate and clamp all setpoints
            decision = self._validate_decision(decision, obs)

            elapsed = time.monotonic() - start
            self._decision_count += 1
            self._last_decision_time = time.monotonic()
            logger.info(
                "LLM decision #%d in %.1fs: mode=%s, fan=%s, confidence=%.0f%%",
                self._decision_count,
                elapsed,
                decision.energy_mode,
                decision.fan_speed,
                decision.confidence * 100,
            )
            return decision

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("LLM decision error: %s — using rule-based fallback.", exc)

        fallback = _rule_based_decision(obs)
        fallback.reasoning = "[Fallback] " + fallback.reasoning
        return fallback

    def _validate_decision(
        self, decision: AgentDecision, obs: BuildingObservation
    ) -> AgentDecision:
        """Clamp setpoints to safe ranges and ensure gap between cool/heat."""
        zones_clean: Dict[str, ZoneSetpoint] = {}
        for zone in settings.ZONES:
            if zone in decision.zone_setpoints:
                sp = decision.zone_setpoints[zone]
            else:
                # Fill missing zones from current observation
                current = obs.zones.get(zone)
                sp = ZoneSetpoint(
                    cooling=current.setpoint_cooling if current else settings.COOLING_SETPOINT_DEFAULT,
                    heating=current.setpoint_heating if current else settings.HEATING_SETPOINT_DEFAULT,
                )

            cool = max(settings.COOLING_SETPOINT_MIN, min(settings.COOLING_SETPOINT_MAX, sp.cooling))
            heat = max(settings.HEATING_SETPOINT_MIN, min(settings.HEATING_SETPOINT_MAX, sp.heating))
            if cool <= heat + 1.5:
                cool = heat + 2.0
            zones_clean[zone] = ZoneSetpoint(cooling=round(cool, 1), heating=round(heat, 1))

        decision.zone_setpoints = zones_clean
        decision.confidence = max(0.0, min(1.0, decision.confidence))
        decision.estimated_savings_pct = max(0.0, min(50.0, decision.estimated_savings_pct))
        return decision

    def get_stats(self) -> dict:
        return {
            "available": self._available,
            "model": self._model,
            "decisions_made": self._decision_count,
            "last_decision_seconds_ago": (
                round(time.monotonic() - self._last_decision_time, 1)
                if self._last_decision_time
                else None
            ),
        }


# ── Module-level singleton ────────────────────────────────────────────────────
agent = BuildingAIAgent()
