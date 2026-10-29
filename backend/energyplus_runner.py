"""
backend/energyplus_runner.py
────────────────────────────
EnergyPlus integration with automatic fallback to a physics-based simulator.

Architecture
────────────
BuildingEnvironment (ABC)
  ├── SimulatedBuildingEnvironment   ← default; no EnergyPlus required
  └── EnergyPlusBuildingEnvironment  ← real EnergyPlus Python API

Use create_environment(settings) to get the right implementation.

Simulated environment
─────────────────────
• 5-zone office building (Core + 4 Perimeters)
• Thermal-mass model:  ΔT = ΣQ · Δt / (ρ · Cp · V)
• Weather: realistic seasonal + diurnal sine-wave model
• Occupancy: office-hours schedule (0 on weekends)
• Solar gains: orientation-aware per zone
• HVAC: proportional controller with COP 3.5 (cooling) / 1.0 (heating)
• PMV/PPD: simplified Fanger ISO 7730 model
"""
from __future__ import annotations

import asyncio
import logging
import math
import random
import sys
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, Optional

from backend.models import BuildingObservation, ZoneState
from config.settings import settings

logger = logging.getLogger(__name__)

# ── Building physical constants ───────────────────────────────────────────────
ZONES = settings.ZONES

# Zone floor areas (m²) — typical medium-size office
ZONE_AREA: Dict[str, float] = {
    "Core":         400.0,
    "Perimeter_N":  150.0,
    "Perimeter_S":  150.0,
    "Perimeter_E":  100.0,
    "Perimeter_W":  100.0,
}

FLOOR_HEIGHT_M = 3.5  # metres

# Air thermal properties
AIR_DENSITY  = 1.204   # kg/m³ at 20 °C
AIR_CP       = 1005.0  # J/(kg·K)

# ── THERMAL MASS CORRECTION ────────────────────────────────────────────────────
# Real office buildings store heat in walls (concrete/drywall), floor slabs,
# furniture, and equipment — not just air.
# Typical effective thermal mass: 100–200 kJ/(m²·K) of floor area.
# Air alone gives ~4 kJ/(m²·K).  Factor of ~30–40 for medium-weight construction.
THERMAL_MASS_MULTIPLIER = 30.0  # accounts for walls, slab, furniture, equipment

THERMAL_MASS: Dict[str, float] = {
    z: AIR_DENSITY * AIR_CP * ZONE_AREA[z] * FLOOR_HEIGHT_M * THERMAL_MASS_MULTIPLIER
    for z in ZONES
}
# Core: ~50,800 kJ/K  (≈ 127 kJ/m²K × 400 m²) — realistic for office slab

# Envelope UA values  W/K  (higher for perimeter zones)
ENVELOPE_UA: Dict[str, float] = {
    "Core":         20.0,
    "Perimeter_N": 120.0,
    "Perimeter_S": 120.0,
    "Perimeter_E":  90.0,
    "Perimeter_W":  90.0,
}

# Max HVAC capacity  W  (80 W/m² cooling, 60 W/m² heating — typical VAV sizing)
MAX_HVAC_COOLING: Dict[str, float] = {z: a * 80.0 for z, a in ZONE_AREA.items()}
MAX_HVAC_HEATING: Dict[str, float] = {z: a * 60.0 for z, a in ZONE_AREA.items()}

HVAC_COP_COOLING = 3.5   # coefficient of performance (cooling)
HVAC_COP_HEATING = 1.0   # electric resistance heating

# Internal gains — ASHRAE 90.1 office values
LIGHTING_WPM2  = 9.0     # W/m²  (LED office lighting)
EQUIPMENT_WPM2 = 10.0    # W/m²  (computers, monitors — reduced from peak)
OCCUPANT_W     = 75.0    # W/person (sensible heat at office activity)
ZONE_DENSITY   = 0.07    # persons/m²  (ASHRAE 62.1: 5 per 1000 ft² ≈ 0.054; use 0.07)


# ══ Sub-models ════════════════════════════════════════════════════════════════

class WeatherModel:
    """Synthetic outdoor conditions based on location and calendar time."""

    def __init__(
        self,
        latitude: float = settings.LOCATION_LATITUDE,
        annual_mean_c: float = 10.0,
        annual_amplitude_c: float = 12.0,
        seed: Optional[int] = None,
    ) -> None:
        self.latitude = latitude
        self.annual_mean_c = annual_mean_c
        self.annual_amplitude_c = annual_amplitude_c
        self._rng = random.Random(seed) if seed is not None else random.Random()

    def get_conditions(self, dt: datetime) -> tuple[float, float]:
        """Return (outdoor_temp_°C, relative_humidity_%)."""
        doy = dt.timetuple().tm_yday
        # Seasonal: peaks in summer (~July 15 = day 196)
        seasonal = self.annual_amplitude_c * math.sin(
            2 * math.pi * (doy - 80) / 365
        )
        # Diurnal: peaks at ~15:00
        hour_frac = dt.hour + dt.minute / 60.0
        diurnal = 5.0 * math.sin(2 * math.pi * (hour_frac - 6.0) / 24.0)
        temp = self.annual_mean_c + seasonal + diurnal + self._rng.gauss(0, 0.3)

        # Humidity roughly anti-correlated with temperature
        humidity = 65.0 - seasonal * 0.8 + self._rng.gauss(0, 3.0)
        humidity = max(20.0, min(95.0, humidity))
        return temp, humidity


class OccupancySchedule:
    """Office occupancy profile (fraction 0–1)."""

    # hour → fraction (interpolated between breakpoints)
    _WEEKDAY: Dict[int, float] = {
        0: 0.0, 6: 0.0, 7: 0.15, 8: 0.55, 9: 0.90,
        10: 1.0, 11: 1.0, 12: 0.65, 13: 0.80, 14: 1.0,
        15: 1.0, 16: 0.85, 17: 0.60, 18: 0.25, 19: 0.08,
        20: 0.0, 23: 0.0,
    }

    def get(self, dt: datetime) -> float:
        if dt.weekday() >= 5:
            return 0.0
        hour = dt.hour + dt.minute / 60.0
        keys = sorted(self._WEEKDAY)
        for i, k in enumerate(keys):
            if hour <= k:
                if i == 0:
                    return self._WEEKDAY[k]
                prev = keys[i - 1]
                t = (hour - prev) / (k - prev)
                return self._WEEKDAY[prev] + t * (self._WEEKDAY[k] - self._WEEKDAY[prev])
        return 0.0


def _solar_gain_wpm2(zone: str, dt: datetime) -> float:
    """Orientation-aware solar gain (W/m²)."""
    hour = dt.hour + dt.minute / 60.0
    if hour < 6.0 or hour > 20.0:
        return 0.0
    sun = max(0.0, math.sin(math.pi * (hour - 6.0) / 14.0))
    morning = hour < 12.0
    gains = {
        "Core":         sun * 18.0,
        "Perimeter_N":  sun * 28.0,
        "Perimeter_S":  sun * 85.0,
        "Perimeter_E":  sun * (65.0 if morning else 18.0),
        "Perimeter_W":  sun * (18.0 if morning else 65.0),
    }
    return gains.get(zone, 25.0)


def _pmv_ppd(air_temp: float, humidity: float, met: float = 1.1, clo: float = 0.7) -> tuple[float, float]:
    """
    Predicted Mean Vote / PPD — Fanger 1972 / ISO 7730.

    Defaults: met=1.1 (office work), clo=0.7 (light office clothing).
    Returns (PMV in −3…+3, PPD in 5…100%).
    Neutral PMV=0 occurs near 22–24°C for these defaults.
    """
    ta   = air_temp           # Air dry-bulb (°C)
    tr   = air_temp + 0.5     # Mean radiant temp slightly above air in occupied space
    rh   = max(10.0, min(95.0, humidity))
    va   = 0.1                # Air speed m/s (still air)

    # Saturated water vapour pressure (Pa) via Magnus formula
    psat = 610.7 * math.exp(17.368 * ta / (238.88 + ta))
    pa   = rh / 100.0 * psat  # Partial vapour pressure (Pa)

    M    = met * 58.15        # Metabolic rate W/m²
    W    = 0.0                # External mechanical work
    H    = M - W              # Internal heat production
    Icl  = clo * 0.155        # Clothing thermal resistance m²K/W

    # Clothing area factor (ISO 7730 Table C.1)
    fcl  = 1.00 + 1.29 * Icl if Icl < 0.078 else 1.05 + 0.645 * Icl

    # Mean skin temperature (°C)
    tsk  = 35.7 - 0.028 * H

    # Evaporative & respiratory losses (W/m²)
    Qres  = 0.0014 * M * (34.0 - ta) + 1.7e-5 * M * (5867.0 - pa)
    Qdiff = 3.05e-3 * (5733.0 - 6.99 * M - pa)
    Qsw   = 0.42 * (H - 58.15) if H > 58.15 else 0.0

    # Initial guess for clothing surface temperature tcl
    tcl = ta + (tsk - ta) / (1.0 + 1.7 * Icl)

    # Newton iteration to solve heat balance at clothing outer surface:
    # heat conducted through clothing = radiative + convective surface losses
    for _ in range(10):
        hc = max(2.38 * abs(tcl - ta) ** 0.25, 12.1 * math.sqrt(va))
        rad = 3.96e-8 * fcl * ((tcl + 273.0) ** 4 - (tr + 273.0) ** 4)
        conv = fcl * hc * (tcl - ta)
        if Icl <= 0:
            tcl = tsk
            break
        cond = (tsk - tcl) / Icl
        f = cond - (rad + conv)
        df = -1.0 / Icl - (3.96e-8 * fcl * 4.0 * (tcl + 273.0) ** 3 + fcl * hc)
        tcl -= f / df

    tcl  = max(ta - 10.0, min(ta + 25.0, tcl))
    hc   = max(2.38 * abs(tcl - ta) ** 0.25, 12.1 * math.sqrt(va))
    rad  = 3.96e-8 * fcl * ((tcl + 273.0) ** 4 - (tr + 273.0) ** 4)
    conv = fcl * hc * (tcl - ta)

    # Thermal load L on the body = internal heat - total heat dissipation
    L = H - (rad + conv + Qdiff + Qsw + Qres)

    pmv = (0.303 * math.exp(-0.036 * M) + 0.028) * L
    pmv = max(-3.0, min(3.0, pmv))

    ppd = 100.0 - 95.0 * math.exp(-0.03353 * pmv ** 4 - 0.2179 * pmv ** 2)
    ppd = max(5.0, min(100.0, ppd))
    return pmv, ppd


# ══ Abstract base ═════════════════════════════════════════════════════════════

class BuildingEnvironment(ABC):
    """Common interface for real and simulated building environments."""

    @abstractmethod
    async def step(self) -> BuildingObservation:
        """Advance one simulation timestep and return the new observation."""

    @abstractmethod
    async def set_setpoint(self, zone: str, cooling: float, heating: float) -> bool:
        """Update cooling/heating setpoints for a zone.  Returns True on success."""

    @abstractmethod
    async def set_all_setpoints(self, cooling: float, heating: float) -> None:
        """Apply the same setpoints to every zone."""

    @abstractmethod
    def is_ready(self) -> bool:
        """Return True once the environment is initialised and ready to step."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name for logging."""


# ══ Physics-based simulator ════════════════════════════════════════════════════

class SimulatedBuildingEnvironment(BuildingEnvironment):
    """
    Fast physics-based building simulator.
    Works without any EnergyPlus installation.
    """

    # ── Simulation start (January 1, 08:00) ─────────────────────────────────
    _SIM_START = datetime(2024, 1, 1, 8, 0, 0)

    def __init__(self, is_baseline: bool = False, seed: Optional[int] = None) -> None:
        self._rng       = random.Random(seed) if seed is not None else random.Random()
        self._is_baseline = is_baseline
        self._weather   = WeatherModel(seed=seed)
        self._occupancy = OccupancySchedule()
        self._ts_min    = settings.TIMESTEP_MINUTES
        self._dt_s      = self._ts_min * 60.0          # timestep seconds

        # State
        self._sim_dt    = self._SIM_START
        cool_init = settings.BASELINE_SETPOINT_COOLING if is_baseline else settings.COOLING_SETPOINT_DEFAULT
        heat_init = settings.BASELINE_SETPOINT_HEATING if is_baseline else settings.HEATING_SETPOINT_DEFAULT

        self._temps     = {z: 21.0 + self._rng.uniform(-0.5, 0.5) for z in ZONES}
        self._sp_cool   = {z: cool_init for z in ZONES}
        self._sp_heat   = {z: heat_init for z in ZONES}
        self._energy    = 0.0                           # cumulative kWh
        self._step_n    = 0
        self._lock      = threading.RLock()
        self._ready     = True

        # Fault injection & override handles
        self._fault_injections: Dict[str, Optional[float]] = {}
        self._weather_override: Optional[tuple[float, float]] = None
        self._occupancy_override: Optional[float] = None

        logger.info(
            "SimulatedBuildingEnvironment initialised (timestep=%d min, baseline=%s).",
            self._ts_min,
            self._is_baseline,
        )

    @property
    def name(self) -> str:
        return "Simulated Physics Engine"

    def is_ready(self) -> bool:
        return self._ready

    # ── Fault Injection & Anomaly Emulation ──────────────────────────────
    def inject_sensor_fault(self, zone: str, value: Optional[float] = None) -> None:
        """Inject a sensor anomaly (NaN, disconnect, or out-of-range value) into a zone."""
        with self._lock:
            self._fault_injections[zone] = value

    def clear_sensor_fault(self, zone: str) -> None:
        """Clear sensor fault injection for a zone."""
        with self._lock:
            self._fault_injections.pop(zone, None)

    def inject_weather_override(self, temp: float, humidity: float = 50.0) -> None:
        """Inject extreme outdoor temperature or humidity."""
        with self._lock:
            self._weather_override = (temp, humidity)

    def clear_weather_override(self) -> None:
        with self._lock:
            self._weather_override = None

    def inject_occupancy_override(self, occupancy: float) -> None:
        """Inject sudden occupancy step changes."""
        with self._lock:
            self._occupancy_override = max(0.0, min(1.0, occupancy))

    def clear_occupancy_override(self) -> None:
        with self._lock:
            self._occupancy_override = None

    async def step(self) -> BuildingObservation:
        """Advance one timestep using thermal-mass model."""
        await asyncio.sleep(0)   # yield to event loop
        with self._lock:
            return self._step_sync()

    def _step_sync(self) -> BuildingObservation:
        if self._weather_override is not None:
            outdoor_temp, outdoor_hum = self._weather_override
        else:
            outdoor_temp, outdoor_hum = self._weather.get_conditions(self._sim_dt)

        if self._occupancy_override is not None:
            occupancy = self._occupancy_override
        else:
            occupancy = self._occupancy.get(self._sim_dt)

        hvac_total_kw = 0.0
        zones: Dict[str, ZoneState] = {}

        for zone in ZONES:
            raw_temp = self._temps[zone]
            is_fault = False
            raw_val = None

            # Check for simulated fault or physical sensor anomaly
            if zone in self._fault_injections:
                is_fault = True
                fault_val = self._fault_injections[zone]
                raw_val = fault_val
                if fault_val is None or math.isnan(fault_val) or fault_val < 5.0 or fault_val > 45.0:
                    # Impute using healthy zone mean
                    healthy = [t for z, t in self._temps.items() if z not in self._fault_injections and 15.0 <= t <= 30.0]
                    temp = sum(healthy) / len(healthy) if healthy else 21.5
                    logger.warning("Sensor fault detected in %s (raw=%s). Imputed %.2f°C.", zone, fault_val, temp)
                else:
                    temp = fault_val
            elif math.isnan(raw_temp) or raw_temp < 5.0 or raw_temp > 45.0:
                is_fault = True
                raw_val = raw_temp
                temp = 21.5
                logger.warning("Sensor anomaly in %s (raw=%.2f). Imputed 21.50°C.", zone, raw_temp)
            else:
                temp = raw_temp

            sp_cool = self._sp_cool[zone]
            sp_heat = self._sp_heat[zone]
            area    = ZONE_AREA[zone]

            # ── Heat gains ───────────────────────────────────────────────────
            Q_solar    = _solar_gain_wpm2(zone, self._sim_dt) * area
            Q_lighting = LIGHTING_WPM2 * area
            Q_equip    = EQUIPMENT_WPM2 * area * (0.3 + 0.7 * occupancy)
            Q_people   = OCCUPANT_W * area * ZONE_DENSITY * occupancy
            Q_internal = Q_lighting + Q_equip + Q_people

            # ── Envelope loss ────────────────────────────────────────────────
            Q_env = -ENVELOPE_UA[zone] * (temp - outdoor_temp)

            # ── HVAC heat exchange ───────────────────────────────────────────
            Q_hvac    = 0.0
            hvac_kw   = 0.0
            deadband  = 0.5   # °C deadband around setpoints

            if temp > sp_cool + deadband:
                # Proportional cooling
                err    = temp - sp_cool
                Q_hvac = -min(MAX_HVAC_COOLING[zone], 200.0 * area * err)
                hvac_kw = abs(Q_hvac) / (HVAC_COP_COOLING * 1000.0)
            elif temp < sp_heat - deadband:
                # Proportional heating
                err    = sp_heat - temp
                Q_hvac = min(MAX_HVAC_HEATING[zone], 150.0 * area * err)
                hvac_kw = abs(Q_hvac) / (HVAC_COP_HEATING * 1000.0)

            hvac_total_kw += hvac_kw

            # ── Thermal mass update ──────────────────────────────────────────
            Q_total = Q_solar + Q_internal + Q_env + Q_hvac
            dT      = Q_total * self._dt_s / THERMAL_MASS[zone]
            self._temps[zone] = round(temp + dT + self._rng.gauss(0, 0.02), 4)

            # ── Zone humidity (simplified) ───────────────────────────────────
            zone_hum = outdoor_hum * 0.75 + self._rng.gauss(0, 1.5)
            zone_hum = max(20.0, min(70.0, zone_hum))

            pmv, ppd = _pmv_ppd(self._temps[zone], zone_hum, met=1.1, clo=0.7)

            # Format raw sensor reading if fault occurred
            recorded_raw = None
            if is_fault and raw_val is not None and not math.isnan(raw_val):
                recorded_raw = round(float(raw_val), 2)

            zones[zone] = ZoneState(
                zone_id=zone,
                temperature=round(self._temps[zone], 2),
                setpoint_cooling=sp_cool,
                setpoint_heating=sp_heat,
                pmv_score=round(pmv, 3),
                ppd_score=round(ppd, 1),
                humidity=round(zone_hum, 1),
                sensor_fault=is_fault,
                raw_temperature=recorded_raw,
            )

        # Cumulative energy
        step_kwh           = hvac_total_kw * (self._ts_min / 60.0)
        self._energy       += step_kwh
        wall_time           = datetime.now(timezone.utc)
        sim_time            = self._sim_dt
        self._sim_dt       += timedelta(minutes=self._ts_min)
        self._step_n       += 1

        return BuildingObservation(
            timestamp=wall_time,
            simulation_time=sim_time,
            zones=zones,
            outdoor_temp=round(outdoor_temp, 2),
            outdoor_humidity=round(outdoor_hum, 1),
            total_energy_kwh=round(self._energy, 3),
            hvac_power_kw=round(hvac_total_kw, 2),
            occupancy=round(occupancy, 3),
            timestep=self._step_n,
        )

    async def set_setpoint(self, zone: str, cooling: float, heating: float) -> bool:
        if self._is_baseline:
            logger.debug("Setpoint change rejected: environment is running fixed baseline.")
            return False
        if zone not in ZONES:
            logger.warning("Unknown zone: %s", zone)
            return False
        if cooling < settings.COOLING_SETPOINT_MIN or cooling > settings.COOLING_SETPOINT_MAX:
            logger.warning("Cooling setpoint %.1f outside valid range [%.1f, %.1f]", cooling, settings.COOLING_SETPOINT_MIN, settings.COOLING_SETPOINT_MAX)
            return False
        if heating < settings.HEATING_SETPOINT_MIN or heating > settings.HEATING_SETPOINT_MAX:
            logger.warning("Heating setpoint %.1f outside valid range [%.1f, %.1f]", heating, settings.HEATING_SETPOINT_MIN, settings.HEATING_SETPOINT_MAX)
            return False
        if cooling < heating + 1.5:
            logger.warning("Deadband violation: cooling (%.1f) must be >= heating (%.1f) + 1.5", cooling, heating)
            return False
        with self._lock:
            self._sp_cool[zone] = cooling
            self._sp_heat[zone] = heating
        logger.debug("Setpoint updated: %s → cool=%.1f heat=%.1f", zone, cooling, heating)
        return True

    async def set_all_setpoints(self, cooling: float, heating: float) -> None:
        for zone in ZONES:
            await self.set_setpoint(zone, cooling, heating)


# ══ Real EnergyPlus environment ════════════════════════════════════════════════

class EnergyPlusBuildingEnvironment(BuildingEnvironment):
    """
    Wraps the EnergyPlus Python API for runtime co-simulation.

    Registers EnergyPlus callbacks to:
    • Read zone temperatures, HVAC energy, and outdoor conditions each timestep.
    • Apply thermostat setpoints via EMS actuators.

    The simulation runs in a daemon thread; step() waits on a threading.Event
    that the callback signals when data is ready.
    """

    def __init__(self) -> None:
        ep_path = Path(settings.ENERGYPLUS_PATH)
        if not ep_path.exists():
            raise FileNotFoundError(
                f"EnergyPlus not found at '{ep_path}'. "
                "Install EnergyPlus or set SIMULATION_MODE=true."
            )

        if str(ep_path) not in sys.path:
            sys.path.insert(0, str(ep_path))

        try:
            from pyenergyplus.api import EnergyPlusAPI  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "pyenergyplus not importable. "
                "Ensure EnergyPlus 9.6+ is installed and ENERGYPLUS_PATH is correct."
            ) from exc

        self._api    = EnergyPlusAPI()
        self._state  = self._api.state_manager.new_state()
        self._lock   = threading.RLock()
        self._ready_event   = threading.Event()
        self._step_event    = threading.Event()

        # Shared buffer written by callback, read by step()
        self._latest_obs: Optional[BuildingObservation] = None

        # Pending setpoint changes applied on next callback
        self._pending_sp: Dict[str, tuple[float, float]] = {}

        # EMS actuator / sensor handles (initialised in callback once API ready)
        self._handles_init    = False
        self._temp_handles:   Dict[str, int] = {}
        self._cool_sp_handles: Dict[str, int] = {}
        self._heat_sp_handles: Dict[str, int] = {}

        self._sim_thread: Optional[threading.Thread] = None
        self._is_ready = False
        self._step_n   = 0
        self._energy   = 0.0

        logger.info("EnergyPlusBuildingEnvironment initialised (EP at %s).", ep_path)

    @property
    def name(self) -> str:
        return "EnergyPlus Python API"

    def is_ready(self) -> bool:
        return self._is_ready

    def start(self) -> None:
        """Launch EnergyPlus in a daemon thread."""
        self._sim_thread = threading.Thread(
            target=self._run_energyplus, daemon=True, name="energyplus-sim"
        )
        self._sim_thread.start()
        # Wait until the first callback fires and marks environment ready
        self._ready_event.wait(timeout=30.0)

    def _run_energyplus(self) -> None:
        api   = self._api
        state = self._state

        # Register callbacks
        api.runtime.callback_begin_system_timestep_before_predictor(
            state, self._timestep_callback
        )

        args = [
            "--idf",     settings.IDF_FILE,
            "--output-directory", "output",
        ]
        if settings.WEATHER_FILE:
            args += ["--weather", settings.WEATHER_FILE]

        logger.info("Starting EnergyPlus simulation …")
        api.runtime.run_energyplus(state, args)
        logger.info("EnergyPlus simulation completed.")

    def _timestep_callback(self, state) -> None:
        api = self._api
        if not api.exchange.api_data_fully_ready(state):
            return

        # Initialise handles once
        if not self._handles_init:
            self._init_handles(state)
            self._is_ready = True
            self._ready_event.set()

        # Apply pending setpoints
        with self._lock:
            pending = dict(self._pending_sp)
            self._pending_sp.clear()

        for zone, (cool, heat) in pending.items():
            if zone in self._cool_sp_handles:
                api.exchange.set_actuator_value(state, self._cool_sp_handles[zone], cool)
                api.exchange.set_actuator_value(state, self._heat_sp_handles[zone], heat)

        # Read temperatures
        zones: Dict[str, ZoneState] = {}
        for zone in ZONES:
            temp = api.exchange.get_variable_value(state, self._temp_handles[zone])
            # Simplified – setpoints and comfort computed from last known values
            sp_cool = api.exchange.get_variable_value(state, self._cool_sp_handles[zone])
            sp_heat = api.exchange.get_variable_value(state, self._heat_sp_handles[zone])
            pmv, ppd = _pmv_ppd(temp, 50.0)
            zones[zone] = ZoneState(
                zone_id=zone,
                temperature=round(temp, 2),
                setpoint_cooling=round(sp_cool, 1),
                setpoint_heating=round(sp_heat, 1),
                pmv_score=round(pmv, 3),
                ppd_score=round(ppd, 1),
                humidity=50.0,
            )

        # Read energy meter (convert J → kWh)
        energy_j = api.exchange.get_meter_value(state, "Electricity:Facility")
        self._energy = energy_j / 3_600_000.0

        # Current simulation time
        year  = api.exchange.year(state)
        month = api.exchange.month(state)
        day   = api.exchange.day_of_month(state)
        hour  = api.exchange.hour(state)
        minute= api.exchange.minutes(state)
        sim_dt = datetime(year, month, day, hour, minute)

        self._step_n += 1
        obs = BuildingObservation(
            timestamp=datetime.now(timezone.utc),
            simulation_time=sim_dt,
            zones=zones,
            outdoor_temp=api.exchange.get_variable_value(state, self._outdoor_temp_handle),
            outdoor_humidity=50.0,
            total_energy_kwh=round(self._energy, 3),
            hvac_power_kw=0.0,     # not easily available per-timestep from meter
            occupancy=0.8,
            timestep=self._step_n,
        )
        with self._lock:
            self._latest_obs = obs
        self._step_event.set()

    def _init_handles(self, state) -> None:
        api = self._api
        for zone in ZONES:
            ep_zone = zone.replace("_", " ")
            self._temp_handles[zone] = api.exchange.get_variable_handle(
                state, "Zone Mean Air Temperature", ep_zone
            )
            self._cool_sp_handles[zone] = api.exchange.get_actuator_handle(
                state, "Zone Temperature Control", "Cooling Setpoint", ep_zone
            )
            self._heat_sp_handles[zone] = api.exchange.get_actuator_handle(
                state, "Zone Temperature Control", "Heating Setpoint", ep_zone
            )
        self._outdoor_temp_handle = api.exchange.get_variable_handle(
            state, "Site Outdoor Air Drybulb Temperature", "Environment"
        )
        self._handles_init = True
        logger.info("EnergyPlus API handles initialised for %d zones.", len(ZONES))

    async def step(self) -> BuildingObservation:
        """Wait for EnergyPlus to complete its next timestep and return the observation."""
        self._step_event.clear()
        # Wait in executor so we don't block the event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._step_event.wait, 30.0)
        with self._lock:
            obs = self._latest_obs
        if obs is None:
            raise RuntimeError("EnergyPlus did not produce an observation within timeout.")
        return obs

    async def set_setpoint(self, zone: str, cooling: float, heating: float) -> bool:
        if zone not in ZONES:
            return False
        with self._lock:
            self._pending_sp[zone] = (cooling, heating)
        return True

    async def set_all_setpoints(self, cooling: float, heating: float) -> None:
        with self._lock:
            for zone in ZONES:
                self._pending_sp[zone] = (cooling, heating)


# ══ Factory ════════════════════════════════════════════════════════════════════

def create_environment() -> BuildingEnvironment:
    """
    Return the appropriate building environment.

    Priority:
    1. If SIMULATION_MODE=true → SimulatedBuildingEnvironment
    2. If SIMULATION_MODE=false → EnergyPlusBuildingEnvironment
       (falls back to simulated if EnergyPlus is unavailable)
    """
    if settings.SIMULATION_MODE:
        logger.info("Using SimulatedBuildingEnvironment (SIMULATION_MODE=true).")
        return SimulatedBuildingEnvironment()

    try:
        env = EnergyPlusBuildingEnvironment()
        logger.info("Using EnergyPlusBuildingEnvironment.")
        return env
    except (FileNotFoundError, ImportError) as exc:
        logger.warning(
            "Cannot initialise EnergyPlus (%s). Falling back to simulation.", exc
        )
        return SimulatedBuildingEnvironment()
