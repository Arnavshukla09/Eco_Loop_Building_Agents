"""
backend/controller.py
──────────────────────
Autonomous HVAC control loop.

Cycle (every AGENT_INTERVAL_SECONDS wall-clock seconds):
  1. Read current building observation from the environment.
  2. Update shared state store.
  3. Call the LLM agent to produce a decision.
  4. Validate and apply setpoints to the environment.
  5. Store the decision in state.
  6. (WebSocket broadcast happens independently via broadcast_loop.)

The controller owns the BuildingEnvironment instance, which is the reference
the MCP tools use via controller.env.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from backend.energyplus_runner import BuildingEnvironment, SimulatedBuildingEnvironment, create_environment
from backend.llm_agent import agent
from backend.models import AgentDecision, BuildingObservation
from backend.state import state_store
from config.settings import settings

logger = logging.getLogger(__name__)


class AutonomousController:
    """
    Orchestrates the simulation → AI → actuation closed loop.

    Attributes
    ----------
    env :   The active BuildingEnvironment (simulated or real EnergyPlus).
    """

    def __init__(self) -> None:
        self.env: Optional[BuildingEnvironment] = None
        self.baseline_env: Optional[BuildingEnvironment] = None
        self._running   = False
        self._sim_task:   Optional[asyncio.Task] = None
        self._agent_task: Optional[asyncio.Task] = None
        self._step_count  = 0
        self._agent_count = 0

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Initialise environment and launch background tasks."""
        logger.info("Initialising building environment …")
        self.env = create_environment()
        logger.info("Using environment: %s", self.env.name)

        if isinstance(self.env, SimulatedBuildingEnvironment):
            self.baseline_env = SimulatedBuildingEnvironment(is_baseline=True)
            logger.info("Parallel fixed-setpoint reference baseline initialised.")
        else:
            self.baseline_env = None

        state_store.set_simulation_running(True)
        state_store.set_llm_available(agent.is_available)

        self._running = True

        # Simulation loop: advances the environment at simulation speed
        self._sim_task = asyncio.create_task(
            self._simulation_loop(), name="simulation-loop"
        )

        # Agent loop: calls LLM every AGENT_INTERVAL_SECONDS
        self._agent_task = asyncio.create_task(
            self._agent_loop(), name="agent-loop"
        )

        step_wall_time = settings.TIMESTEP_MINUTES * 60.0 / settings.SPEEDUP_FACTOR
        logger.info(
            "Controller started. Sim interval: %.2f s wall-clock per step (%.0f min simulated, ×%.1f speedup). "
            "Agent interval: %.0f s.",
            step_wall_time,
            settings.TIMESTEP_MINUTES,
            settings.SPEEDUP_FACTOR,
            settings.AGENT_INTERVAL_SECONDS,
        )

    async def stop(self) -> None:
        """Gracefully cancel all background tasks."""
        self._running = False
        for task in (self._sim_task, self._agent_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        state_store.set_simulation_running(False)
        logger.info("Controller stopped.")

    # ── Simulation loop ────────────────────────────────────────────────────────

    async def _simulation_loop(self) -> None:
        """
        Advances the simulation one timestep at a time.

        Sleep between steps = TIMESTEP_MINUTES / SPEEDUP_FACTOR seconds.
        Default: 15 min / 60 = 0.25 s per step → 1 simulated day ≈ 6 s wall-clock.
        """
        step_wall_time = settings.TIMESTEP_MINUTES * 60.0 / settings.SPEEDUP_FACTOR
        logger.info(
            "Simulation loop running (%.2f s per %.0f-min timestep).",
            step_wall_time,
            settings.TIMESTEP_MINUTES,
        )

        while self._running:
            try:
                t0  = time.monotonic()
                obs = await self.env.step()
                if self.baseline_env is not None:
                    try:
                        base_obs = await self.baseline_env.step()
                        state_store.update_baseline_energy(base_obs.total_energy_kwh)
                    except Exception as base_exc:
                        logger.warning("Baseline reference step failed: %s", base_exc)
                state_store.update_observation(obs)
                self._step_count += 1

                if self._step_count % 96 == 0:   # log every simulated day
                    logger.info(
                        "Step %d | Sim: %s | Avg Temp: %.1f°C | Energy: %.1f kWh | "
                        "HVAC: %.1f kW",
                        self._step_count,
                        obs.simulation_time.strftime("%Y-%m-%d %H:%M"),
                        obs.avg_temperature,
                        obs.total_energy_kwh,
                        obs.hvac_power_kw,
                    )

                elapsed = time.monotonic() - t0
                sleep   = max(0.0, step_wall_time - elapsed)
                await asyncio.sleep(sleep)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("Simulation step error: %s", exc)
                await asyncio.sleep(1.0)

    # ── Agent loop ─────────────────────────────────────────────────────────────

    async def _agent_loop(self) -> None:
        """
        Calls the LLM agent at regular intervals and applies its decisions.
        """
        # Wait for first observation before starting
        logger.info("Agent loop waiting for first simulation step …")
        for _ in range(60):
            if state_store.get_observation() is not None:
                break
            await asyncio.sleep(0.5)
        else:
            logger.error("Timed out waiting for first observation. Agent loop exiting.")
            return

        logger.info(
            "Agent loop started (interval: %.0f s).", settings.AGENT_INTERVAL_SECONDS
        )

        while self._running:
            try:
                t0 = time.monotonic()

                obs     = state_store.get_observation()
                history = state_store.get_history(limit=20)

                if obs is None:
                    await asyncio.sleep(1.0)
                    continue

                logger.info(
                    "Agent cycle #%d: Sim=%s, Avg=%.1f°C, Occ=%.0f%%",
                    self._agent_count + 1,
                    obs.simulation_time.strftime("%m-%d %H:%M"),
                    obs.avg_temperature,
                    obs.occupancy * 100,
                )

                # Ask LLM for a decision
                decision: AgentDecision = await agent.analyze_and_decide(obs, history)

                # Apply setpoints to environment
                await self._apply_decision(decision)

                # Persist decision in state
                state_store.update_decision(decision)
                state_store.set_llm_available(agent.is_available)

                self._agent_count += 1
                elapsed = time.monotonic() - t0
                sleep   = max(0.0, settings.AGENT_INTERVAL_SECONDS - elapsed)
                await asyncio.sleep(sleep)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("Agent loop error: %s", exc)
                await asyncio.sleep(5.0)

    async def _apply_decision(self, decision: AgentDecision) -> None:
        """Push each zone's setpoints from the decision to the environment."""
        applied = 0
        for zone, sp in decision.zone_setpoints.items():
            ok = await self.env.set_setpoint(zone, sp.cooling, sp.heating)
            if ok:
                applied += 1
        logger.info(
            "Applied setpoints for %d/%d zones. Mode: %s, Fan: %s.",
            applied,
            len(decision.zone_setpoints),
            decision.energy_mode,
            decision.fan_speed,
        )

    # ── Status ─────────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "running":       self._running,
            "sim_steps":     self._step_count,
            "agent_cycles":  self._agent_count,
            "env_name":      self.env.name if self.env else "not initialised",
        }


# ── Module-level singleton ─────────────────────────────────────────────────────
controller = AutonomousController()
