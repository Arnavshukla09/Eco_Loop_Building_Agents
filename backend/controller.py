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
from datetime import timedelta
from typing import Optional

from backend.energyplus_runner import BuildingEnvironment, SimulatedBuildingEnvironment, create_environment
from backend.llm_agent import agent, _rule_based_decision
from backend.models import AgentDecision, BuildingObservation, ZoneSetpoint, validate_setpoints
from backend.providers import BaseDecisionProvider, RuleBasedProvider, ScheduledProvider, ForecastProvider
from backend.repository import repository
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

    def __init__(self, provider: Optional[BaseDecisionProvider] = None) -> None:
        self.env: Optional[BuildingEnvironment] = None
        self.baseline_env: Optional[BuildingEnvironment] = None
        configured = {"rule_based": RuleBasedProvider, "scheduled": ScheduledProvider, "forecast": ForecastProvider}
        self.provider: BaseDecisionProvider = provider or (configured[settings.CONTROL_PROVIDER]() if settings.CONTROL_PROVIDER in configured else agent)
        self._running   = False
        self._sim_task:   Optional[asyncio.Task] = None
        self._agent_task: Optional[asyncio.Task] = None
        self._step_count  = 0
        self._agent_count = 0
        self._step_lock: Optional[asyncio.Lock] = None
        self._current_run_id: Optional[str] = None
        self._generation = 0
        self._persistence_tasks: set[asyncio.Task] = set()
        self._last_command_setpoints: dict[str, dict[str, float]] = {}
        self._manual_overrides: dict[str, dict] = {}

    def _expire_overrides(self) -> None:
        obs = state_store.get_observation()
        if obs:
            self._manual_overrides = {z: hold for z, hold in self._manual_overrides.items() if hold["expires_at"] > obs.simulation_time}

    def control_status(self) -> dict:
        self._expire_overrides()
        return {"provider": self.provider.name, "run_id": self._current_run_id,
                "fan_actuation_supported": isinstance(self.env, SimulatedBuildingEnvironment),
                "overrides": {z: {**hold, "expires_at": hold["expires_at"].isoformat()} for z, hold in self._manual_overrides.items()}}

    async def manual_override(self, zone, cooling, heating, duration_minutes) -> dict:
        """Hold acknowledged values for a defined amount of simulation time."""
        # Reentrant operations are avoided: the setpoint methods take the step lock.
        zones = [zone] if zone else settings.ZONES
        ok = await self.set_zone_setpoint(zone, cooling, heating) if zone else await self.set_all_zone_setpoints(cooling, heating)
        # No await between actuation acknowledgement and installing the hold.
        obs = state_store.get_observation()
        if obs:
            for z, sp in self._last_command_setpoints.items():
                self._manual_overrides[z] = {**sp, "expires_at": obs.simulation_time + timedelta(minutes=duration_minutes)}
        result = self.setpoint_result(zones, cooling, heating, ok)
        result["overrides"] = self.control_status()["overrides"]
        return result

    async def release_override(self, zone=None) -> None:
        async with self.step_lock:
            if zone:
                self._manual_overrides.pop(zone, None)
            else:
                self._manual_overrides.clear()

    def _persist(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self._persistence_tasks.add(task)
        def finished(completed):
            self._persistence_tasks.discard(completed)
            if not completed.cancelled() and completed.exception():
                logger.warning("Persistence failed: %s", completed.exception())
        task.add_done_callback(finished)

    async def _initialise_environment(self) -> None:
        self.env = create_environment()
        await self.env.initialize()
        self.baseline_env = (
            SimulatedBuildingEnvironment(is_baseline=True, seed=self.env.seed)
            if isinstance(self.env, SimulatedBuildingEnvironment) else None
        )
        state_store.set_simulation_mode(isinstance(self.env, SimulatedBuildingEnvironment))

    @property
    def step_lock(self) -> asyncio.Lock:
        if self._step_lock is None:
            self._step_lock = asyncio.Lock()
        return self._step_lock

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Initialise environment and launch background tasks."""
        if self._running:
            return
        logger.info("Initialising building environment …")
        await self._initialise_environment()
        try:
            self._current_run_id = await repository.create_run(baseline_mode="measured" if self.baseline_env else "unmeasured")
        except Exception as exc:
            logger.warning("Database run initialisation deferred: %s", exc)

        logger.info("Using environment: %s", self.env.name)

        state_store.reset()
        self._manual_overrides.clear()
        self._last_command_setpoints = {}
        self._generation += 1
        self._step_count = 0
        self._agent_count = 0

        state_store.set_simulation_running(True)
        state_store.set_llm_available(False)

        self._running = True

        # Simulation loop: advances the environment at simulation speed
        self._sim_task = asyncio.create_task(
            self._simulation_loop(), name="simulation-loop"
        )

        # Agent loop: calls LLM every AGENT_INTERVAL_SECONDS
        self._agent_task = asyncio.create_task(
            self._agent_loop(), name="agent-loop"
        )

        step_wall_time = settings.TIMESTEP_MINUTES * 60.0 / max(1.0, settings.SPEEDUP_FACTOR)
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
        if self.env is not None:
            await self.env.close()
        if self._persistence_tasks:
            await asyncio.gather(*tuple(self._persistence_tasks), return_exceptions=True)

        # Complete run in database if active
        if self._current_run_id:
            try:
                metrics = state_store.get_metrics()
                obs_prev = state_store.get_observation()
                total_kwh = obs_prev.total_energy_kwh if obs_prev else 0.0
                base_kwh = metrics.baseline_energy_kwh if metrics else 0.0
                savings = metrics.energy_savings_pct if metrics else 0.0
                comfort = metrics.comfort_score if metrics else 0.0
                await repository.complete_run(
                    run_id=self._current_run_id,
                    total_steps=self._step_count,
                    total_energy=total_kwh,
                    baseline_energy=base_kwh,
                    savings_pct=savings,
                    comfort_score=comfort,
                )
            except Exception as exc:
                logger.debug("Database run completion on stop skipped: %s", exc)

        logger.info("Controller stopped.")

    # ── Safe Single-Owner Simulation Step ──────────────────────────────────────

    async def step_simulation(self) -> BuildingObservation:
        """
        Safely advance the active simulation and parallel baseline by one timestep.
        Guarded by step_lock to prevent concurrent execution races from the controller
        loop, external MCP calls, and API commands.
        """
        async with self.step_lock:
            if self.env is None:
                raise RuntimeError("Simulation environment not initialised.")

            obs = await self.env.step()
            if self.baseline_env is not None:
                try:
                    base_obs = await self.baseline_env.step()
                    state_store.update_baseline_energy(base_obs.total_energy_kwh, base_obs.hvac_power_kw)
                except Exception as base_exc:
                    logger.warning("Baseline reference step failed: %s", base_exc)
                    state_store.clear_baseline()
                    self.baseline_env = None  # A missed step invalidates the matched reference.
            state_store.update_observation(obs)
            self._expire_overrides()
            state_store.update_control(self.control_status())
            self._step_count += 1

            # Persist reading to database in background
            if self._current_run_id:
                history_entries = state_store.get_history(limit=1)
                if history_entries:
                    try:
                        self._persist(
                            repository.record_reading(
                                self._current_run_id, history_entries[-1], obs.timestep
                            )
                        )
                    except Exception:
                        pass

            return obs

    # ── Simulation loop ────────────────────────────────────────────────────────

    async def _simulation_loop(self) -> None:
        """
        Advances the simulation one timestep at a time.

        Sleep between steps = TIMESTEP_MINUTES / SPEEDUP_FACTOR seconds.
        Recalculated every iteration to immediately reflect runtime speed adjustments.
        """
        logger.info(
            "Simulation loop running (initial speedup: %.1fx).",
            settings.SPEEDUP_FACTOR,
        )

        while self._running:
            try:
                t0 = time.monotonic()
                step_wall_time = settings.TIMESTEP_MINUTES * 60.0 / max(1.0, settings.SPEEDUP_FACTOR)

                obs = await self.step_simulation()

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

                # Query configured provider (Ollama, RuleBased, or Hybrid) via BaseDecisionProvider contract
                async with self.step_lock:
                    generation = self._generation
                    obs = state_store.get_observation()
                    history = state_store.get_history(limit=20)
                if obs is None:
                    continue
                try:
                    decision: AgentDecision = await self.provider.decide(obs, history)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("Decision provider failed; using rule-based fallback: %s", exc)
                    decision = _rule_based_decision(obs)
                    decision.controller_source = "fallback"

                # Apply setpoints to environment
                if not await self._apply_decision(decision, generation):
                    continue

                # Persist decision in state
                state_store.update_decision(decision)
                state_store.set_llm_available(decision.controller_source == "llm")

                self._agent_count += 1
                elapsed = time.monotonic() - t0
                sleep   = max(0.0, settings.AGENT_INTERVAL_SECONDS - elapsed)
                await asyncio.sleep(sleep)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("Agent loop error: %s", exc)
                await asyncio.sleep(5.0)

    def _clamp_setpoint_slew(self, zone: str, cooling: float, heating: float) -> tuple[float, float]:
        """Apply 2°C/cycle slew-rate limit and ensure 1.5°C deadband against current setpoint."""
        MAX_DELTA = 2.0
        current_obs = state_store.get_observation()
        target_cool = cooling
        target_heat = heating
        if current_obs and zone in current_obs.zones:
            curr_z = current_obs.zones[zone]
            target_cool = max(curr_z.setpoint_cooling - MAX_DELTA, min(curr_z.setpoint_cooling + MAX_DELTA, target_cool))
            target_heat = max(curr_z.setpoint_heating - MAX_DELTA, min(curr_z.setpoint_heating + MAX_DELTA, target_heat))
            if target_cool < target_heat + 1.5:
                target_cool = min(settings.COOLING_SETPOINT_MAX, target_heat + 1.5)
        return round(target_cool, 1), round(target_heat, 1)

    async def set_zone_setpoint(self, zone: str, cooling: float, heating: float, force: bool = False) -> bool:
        """Safely update setpoints for a single zone with lock protection, canonical validation, and slew-rate limiting."""
        try:
            validate_setpoints(cooling, heating, zone)
        except ValueError as exc:
            self._last_command_setpoints = {}
            logger.warning("Rejected invalid setpoint for %s (cool=%.1f, heat=%.1f): %s", zone, cooling, heating, exc)
            return False

        async with self.step_lock:
            self._last_command_setpoints = {}
            if self.env is None:
                return False
            if not force:
                target_cool, target_heat = self._clamp_setpoint_slew(zone, cooling, heating)
            else:
                target_cool, target_heat = round(cooling, 1), round(heating, 1)
            try:
                ok = await self.env.set_setpoint(zone, target_cool, target_heat)
            except Exception as exc:
                logger.warning("Setpoint actuation failed for %s: %s", zone, exc)
                return False
            if ok:
                state_store.update_setpoint(zone, target_cool, target_heat)
                self._last_command_setpoints[zone] = {"cooling": target_cool, "heating": target_heat}
            return ok

    async def set_all_zone_setpoints(self, cooling: float, heating: float, force: bool = False) -> bool:
        """Safely update setpoints for all zones with lock protection, canonical validation, and slew-rate limiting."""
        try:
            validate_setpoints(cooling, heating, None)
        except ValueError as exc:
            self._last_command_setpoints = {}
            logger.warning("Rejected invalid setpoints for all zones (cool=%.1f, heat=%.1f): %s", cooling, heating, exc)
            return False

        async with self.step_lock:
            self._last_command_setpoints = {}
            if self.env is None:
                return False
            success = True
            for z in settings.ZONES:
                if not force:
                    target_cool, target_heat = self._clamp_setpoint_slew(z, cooling, heating)
                else:
                    target_cool, target_heat = round(cooling, 1), round(heating, 1)
                try:
                    ok = await self.env.set_setpoint(z, target_cool, target_heat)
                except Exception as exc:
                    logger.warning("Setpoint actuation failed for %s: %s", z, exc)
                    ok = False
                success = success and ok
                if ok:
                    state_store.update_setpoint(z, target_cool, target_heat)
                    self._last_command_setpoints[z] = {"cooling": target_cool, "heating": target_heat}
            return success

    def setpoint_result(self, zones, cooling: float, heating: float, success: bool) -> dict:
        """Describe acknowledged values, preserving distinct setpoints across zones."""
        applied = {z: self._last_command_setpoints[z] for z in zones if z in self._last_command_setpoints}
        pairs = {(sp["cooling"], sp["heating"]) for sp in applied.values()}
        cool, heat = next(iter(pairs)) if len(pairs) == 1 else (None, None)
        return {
            "success": success, "cooling_c": cool, "heating_c": heat,
            "requested": {"cooling": cooling, "heating": heating},
            "applied_setpoints": applied,
            "actuation_status": "queued" if applied and not isinstance(self.env, SimulatedBuildingEnvironment) else ("applied" if success else "partial" if applied else "failed"),
        }

    async def reset_simulation(self) -> BuildingObservation:
        """
        Safely reset both active simulation and parallel baseline to step 0.
        Guarded by step_lock to prevent race conditions with background loops.
        Archives previous run statistics in database and starts a fresh active run.
        """
        async with self.step_lock:
            self._generation += 1
            self._manual_overrides.clear()
            if self._persistence_tasks:
                await asyncio.gather(*tuple(self._persistence_tasks), return_exceptions=True)
            if self._current_run_id:
                try:
                    metrics = state_store.get_metrics()
                    obs_prev = state_store.get_observation()
                    total_kwh = obs_prev.total_energy_kwh if obs_prev else 0.0
                    base_kwh = metrics.baseline_energy_kwh if metrics else 0.0
                    savings = metrics.energy_savings_pct if metrics else 0.0
                    comfort = metrics.comfort_score if metrics else 0.0
                    await repository.complete_run(
                        run_id=self._current_run_id,
                        total_steps=self._step_count,
                        total_energy=total_kwh,
                        baseline_energy=base_kwh,
                        savings_pct=savings,
                        comfort_score=comfort,
                    )
                    self._current_run_id = None
                except Exception as exc:
                    logger.warning("Database archiving on reset deferred: %s", exc)

            if self.env is not None:
                await self.env.close()
            await self._initialise_environment()
            try:
                self._current_run_id = await repository.create_run(baseline_mode="measured" if self.baseline_env else "unmeasured")
            except Exception as exc:
                logger.warning("Database run creation on reset deferred: %s", exc)
            self._step_count = 1
            self._agent_count = 0
            state_store.reset()
            state_store.set_llm_available(False)
            obs = await self.env.step()
            if self.baseline_env is not None:
                try:
                    base_obs = await self.baseline_env.step()
                    state_store.update_baseline_energy(base_obs.total_energy_kwh, base_obs.hvac_power_kw)
                except Exception as exc:
                    logger.warning("Baseline reference reset failed: %s", exc)
                    state_store.clear_baseline()
                    self.baseline_env = None
            state_store.update_observation(obs)
            state_store.update_control(self.control_status())
            if self._current_run_id:
                self._persist(repository.record_reading(self._current_run_id, state_store.get_history(1)[0], obs.timestep))
            return obs

    async def _apply_decision(self, decision: AgentDecision, generation: Optional[int] = None) -> bool:
        """Push each zone's setpoints from the decision to the environment under step_lock with slew-rate limiting."""
        applied = 0
        async with self.step_lock:
            if generation is not None and generation != self._generation:
                logger.info("Discarded decision from before simulation reset.")
                return False
            decision.applied_setpoints = {}
            self._expire_overrides()
            for zone, sp in decision.zone_setpoints.items():
                if zone in self._manual_overrides:
                    continue
                try:
                    validate_setpoints(sp.cooling, sp.heating, zone)
                except ValueError:
                    continue
                target_cool, target_heat = self._clamp_setpoint_slew(zone, sp.cooling, sp.heating)
                if self.env is not None:
                    try:
                        ok = await self.env.set_setpoint(zone, target_cool, target_heat)
                    except Exception as exc:
                        logger.warning("Setpoint actuation failed for %s: %s", zone, exc)
                        continue
                    if ok:
                        state_store.update_setpoint(zone, target_cool, target_heat)
                        decision.applied_setpoints[zone] = ZoneSetpoint(cooling=target_cool, heating=target_heat)
                        applied += 1
            if self.env is not None:
                try:
                    await self.env.set_fan_speed(decision.fan_speed)
                except Exception as exc:
                    logger.warning("Fan actuation failed: %s", exc)
            state_store.update_control(self.control_status())

        requested = len(decision.zone_setpoints)
        held = sum(zone in self._manual_overrides for zone in decision.zone_setpoints)
        if requested and held == requested:
            actuation_status = "held"
        elif applied and applied == requested - held:
            actuation_status = "applied" if not held else "partial"
        else:
            actuation_status = "partial" if applied else "failed"
        if applied and not isinstance(self.env, SimulatedBuildingEnvironment):
            actuation_status = "queued"
        if self._current_run_id:
            obs = state_store.get_observation()
            timestep = obs.timestep if obs else 0
            try:
                self._persist(
                    repository.record_decision(self._current_run_id, decision, timestep, actuation_status)
                )
            except Exception:
                pass

        logger.info(
            "Applied setpoints for %d/%d zones. Mode: %s, Fan: %s.",
            applied,
            len(decision.zone_setpoints),
            decision.energy_mode,
            decision.fan_speed,
        )
        return True

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
