"""
backend/mcp_server.py
──────────────────────
FastMCP server exposing building automation tools.

This MCP server runs embedded within the FastAPI application (mounted at /mcp).
All tools operate on the shared state_store singleton, meaning they always
return live data regardless of whether EnergyPlus or the simulator is running.

Tools exposed
─────────────
1.  read_building_state     → current temps, setpoints, energy, comfort
2.  get_hvac_setpoints      → current setpoints per zone
3.  update_setpoint         → change a single zone's setpoints
4.  update_all_setpoints    → change all zones at once
5.  run_simulation_step     → trigger the controller to advance one step
6.  get_energy_usage        → cumulative energy + power draw
7.  calculate_savings       → energy savings vs baseline
8.  get_comfort_report      → PMV/PPD per zone
9.  get_outdoor_conditions  → outdoor temp, humidity, time
10. get_ai_decision         → last AI decision + reasoning

MCP transport: SSE (Server-Sent Events over HTTP)
Access URL:    http://localhost:8001/sse   (standalone)
               http://localhost:8000/mcp/  (mounted on FastAPI)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastmcp import FastMCP

from config.settings import settings

logger = logging.getLogger(__name__)

# Create the FastMCP server instance
mcp = FastMCP(
    name="EcoLoop Building Automation MCP",
    instructions=(
        "This MCP server provides tools to monitor and control a smart building's "
        "HVAC system in real time. Use read_building_state first to get an overview, "
        "then use update_setpoint or update_all_setpoints to adjust thermostats."
    ),
)


# ── Helper: late-import state_store to avoid circular imports ─────────────────

def _state():
    from backend.state import state_store
    return state_store


def _env():
    from backend.controller import controller
    return controller.env if controller is not None else None


# ══ Tool definitions ═══════════════════════════════════════════════════════════

@mcp.tool()
def read_building_state() -> Dict[str, Any]:
    """
    Get the complete current state of the building including all zone temperatures,
    setpoints, comfort indices, energy consumption, and outdoor conditions.
    Returns real-time data from the simulation.
    """
    store = _state()
    obs   = store.get_observation()
    if obs is None:
        return {"error": "Simulation not started yet. Waiting for first timestep."}

    zones_data = {}
    for name, zone in obs.zones.items():
        zones_data[name] = {
            "temperature_c":       zone.temperature,
            "setpoint_cooling_c":  zone.setpoint_cooling,
            "setpoint_heating_c":  zone.setpoint_heating,
            "pmv_score":           zone.pmv_score,
            "ppd_percent":         zone.ppd_score,
            "humidity_percent":    zone.humidity,
            "comfort_status":      zone.comfort_label,
        }

    return {
        "simulation_time":    obs.simulation_time.isoformat(),
        "zones":              zones_data,
        "outdoor_temp_c":     obs.outdoor_temp,
        "outdoor_humidity":   obs.outdoor_humidity,
        "total_energy_kwh":   obs.total_energy_kwh,
        "hvac_power_kw":      obs.hvac_power_kw,
        "occupancy_fraction": obs.occupancy,
        "timestep":           obs.timestep,
    }


@mcp.tool()
def get_hvac_setpoints() -> Dict[str, Any]:
    """
    Return the active heating and cooling setpoints for every HVAC zone.
    """
    store = _state()
    setpoints = store.get_current_setpoints()
    return {
        zone: {
            "cooling_setpoint_c": sp.cooling,
            "heating_setpoint_c": sp.heating,
            "deadband_c":         round(sp.cooling - sp.heating, 1),
        }
        for zone, sp in setpoints.items()
    }


@mcp.tool()
async def update_setpoint(zone: str, cooling_c: float, heating_c: float) -> Dict[str, Any]:
    """
    Update the cooling and heating setpoints for a specific zone.

    Args:
        zone:       Zone name (e.g. 'Core', 'Perimeter_N'). Case-sensitive.
        cooling_c:  New cooling setpoint in °C (must be > heating_c + 2).
        heating_c:  New heating setpoint in °C.

    Returns a confirmation dict with the applied values.
    """
    if zone not in settings.ZONES:
        return {
            "success": False,
            "error": f"Unknown zone '{zone}'. Valid zones: {settings.ZONES}",
        }

    # Clamp to safe range
    cooling_c = max(settings.COOLING_SETPOINT_MIN, min(settings.COOLING_SETPOINT_MAX, cooling_c))
    heating_c = max(settings.HEATING_SETPOINT_MIN, min(settings.HEATING_SETPOINT_MAX, heating_c))
    if cooling_c <= heating_c + 1.5:
        cooling_c = heating_c + 2.0

    env = _env()
    if env is not None:
        success = await env.set_setpoint(zone, cooling_c, heating_c)
    else:
        success = False

    return {
        "success":    success,
        "zone":       zone,
        "cooling_c":  round(cooling_c, 1),
        "heating_c":  round(heating_c, 1),
        "message":    f"Setpoint updated for {zone}." if success else "Controller not running.",
    }


@mcp.tool()
async def update_all_setpoints(cooling_c: float, heating_c: float) -> Dict[str, Any]:
    """
    Apply the same cooling and heating setpoints to ALL zones simultaneously.

    Args:
        cooling_c:  New cooling setpoint in °C for all zones.
        heating_c:  New heating setpoint in °C for all zones.
    """
    cooling_c = max(settings.COOLING_SETPOINT_MIN, min(settings.COOLING_SETPOINT_MAX, cooling_c))
    heating_c = max(settings.HEATING_SETPOINT_MIN, min(settings.HEATING_SETPOINT_MAX, heating_c))
    if cooling_c <= heating_c + 1.5:
        cooling_c = heating_c + 2.0

    env = _env()
    if env is not None:
        await env.set_all_setpoints(cooling_c, heating_c)
        return {
            "success":     True,
            "zones_updated": settings.ZONES,
            "cooling_c":   round(cooling_c, 1),
            "heating_c":   round(heating_c, 1),
        }
    return {"success": False, "error": "Controller not running."}


@mcp.tool()
def get_energy_usage() -> Dict[str, Any]:
    """
    Return detailed energy consumption data including cumulative usage,
    current power draw, and energy efficiency metrics.
    """
    store   = _state()
    obs     = store.get_observation()
    metrics = store.get_metrics()
    if obs is None:
        return {"error": "No data available yet."}

    return {
        "total_energy_kwh":     obs.total_energy_kwh,
        "hvac_power_kw":        obs.hvac_power_kw,
        "peak_demand_kw":       metrics.peak_demand_kw if metrics else 0.0,
        "energy_per_area_kwh_m2": round(
            obs.total_energy_kwh / sum([400, 150, 150, 100, 100]), 4
        ),
        "simulation_time":      obs.simulation_time.isoformat(),
        "timestep":             obs.timestep,
    }


@mcp.tool()
def calculate_savings() -> Dict[str, Any]:
    """
    Calculate energy savings achieved by the AI agent compared to a fixed
    baseline schedule (cooling=22°C, heating=21°C, always-on).

    Returns savings in kWh, percentage, and estimated CO₂ avoided.
    """
    store   = _state()
    metrics = store.get_metrics()
    if metrics is None:
        return {"error": "No data available yet."}

    return {
        "current_energy_kwh":   metrics.current_energy_kwh,
        "baseline_energy_kwh":  metrics.baseline_energy_kwh,
        "savings_kwh":          round(metrics.baseline_energy_kwh - metrics.current_energy_kwh, 3),
        "savings_percent":      metrics.energy_savings_pct,
        "co2_saved_kg":         metrics.co2_saved_kg,
        "co2_intensity_kg_kwh": 0.386,
        "note": (
            "Baseline assumes fixed setpoints (cool=22°C, heat=21°C) with no AI optimisation."
        ),
    }


@mcp.tool()
def get_comfort_report() -> Dict[str, Any]:
    """
    Retrieve a detailed comfort analysis for all zones including PMV scores,
    PPD percentages, and ASHRAE 55 compliance status.
    """
    store = _state()
    obs   = store.get_observation()
    if obs is None:
        return {"error": "No data available yet."}

    comfort_data = {}
    for name, zone in obs.zones.items():
        # ASHRAE 55 comfort zone: PMV between -0.5 and +0.5
        compliant = abs(zone.pmv_score) <= 0.5
        comfort_data[name] = {
            "temperature_c":   zone.temperature,
            "pmv":             zone.pmv_score,
            "ppd_percent":     zone.ppd_score,
            "comfort_label":   zone.comfort_label,
            "ashrae55_compliant": compliant,
            "recommendation":  _comfort_recommendation(zone.pmv_score, zone.temperature),
        }

    avg_pmv  = obs.avg_pmv
    avg_ppd  = obs.avg_ppd
    overall_score = max(0.0, 1.0 - avg_ppd / 100.0)

    return {
        "zones":          comfort_data,
        "building_avg_pmv": round(avg_pmv, 3),
        "building_avg_ppd": round(avg_ppd, 1),
        "comfort_score":  round(overall_score, 3),
        "simulation_time": obs.simulation_time.isoformat(),
    }


def _comfort_recommendation(pmv: float, temp: float) -> str:
    if pmv > 1.5:
        return "Zone is too warm. Lower cooling setpoint or increase ventilation."
    if pmv > 0.5:
        return "Zone is slightly warm. Consider reducing cooling setpoint by 0.5–1°C."
    if pmv < -1.5:
        return "Zone is too cold. Raise heating setpoint."
    if pmv < -0.5:
        return "Zone is slightly cool. Consider increasing heating setpoint by 0.5°C."
    return "Zone is within ASHRAE 55 comfort zone. No action needed."


@mcp.tool()
def get_outdoor_conditions() -> Dict[str, Any]:
    """
    Return current outdoor environmental conditions and simulation time context.
    """
    store = _state()
    obs   = store.get_observation()
    if obs is None:
        return {"error": "No data available yet."}

    hour = obs.simulation_time.hour
    if 6 <= hour < 9:
        period = "morning"
    elif 9 <= hour < 12:
        period = "mid-morning"
    elif 12 <= hour < 14:
        period = "noon"
    elif 14 <= hour < 18:
        period = "afternoon"
    elif 18 <= hour < 22:
        period = "evening"
    else:
        period = "night"

    season_month = obs.simulation_time.month
    if season_month in (12, 1, 2):
        season = "winter"
    elif season_month in (3, 4, 5):
        season = "spring"
    elif season_month in (6, 7, 8):
        season = "summer"
    else:
        season = "autumn"

    return {
        "outdoor_temp_c":    obs.outdoor_temp,
        "outdoor_humidity":  obs.outdoor_humidity,
        "simulation_time":   obs.simulation_time.isoformat(),
        "day_of_week":       obs.simulation_time.strftime("%A"),
        "time_period":       period,
        "season":            season,
        "occupancy_fraction": obs.occupancy,
    }


@mcp.tool()
def get_ai_decision() -> Dict[str, Any]:
    """
    Return the most recent AI agent decision, including setpoints chosen,
    reasoning, and estimated energy savings.
    """
    store    = _state()
    decision = store.get_decision()
    if decision is None:
        return {"error": "No AI decision available yet. Agent has not run."}

    return {
        "zone_setpoints": {
            zone: {"cooling_c": sp.cooling, "heating_c": sp.heating}
            for zone, sp in decision.zone_setpoints.items()
        },
        "fan_speed":          decision.fan_speed,
        "energy_mode":        decision.energy_mode,
        "reasoning":          decision.reasoning,
        "confidence":         decision.confidence,
        "estimated_savings_pct": decision.estimated_savings_pct,
    }
