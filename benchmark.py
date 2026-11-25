"""Matched seasonal benchmark with explicit attribution and occupied comfort metrics."""
import argparse
import asyncio
from datetime import datetime
import json
from pathlib import Path
import statistics
import time

from backend.controller import AutonomousController
from backend.energyplus_runner import SimulatedBuildingEnvironment
from backend.llm_agent import BuildingAIAgent, _rule_based_decision
from backend.providers import ScheduledProvider, ForecastProvider
from backend.state import state_store
from config.settings import settings

SEASONS = {"winter": "2024-01-15T00:00:00", "spring": "2024-04-15T00:00:00", "summer": "2024-07-15T00:00:00", "autumn": "2024-10-14T00:00:00"}


async def scenario(mode, season, seed, steps):
    env = SimulatedBuildingEnvironment(is_baseline=mode == "fixed", seed=seed, start_time=datetime.fromisoformat(SEASONS[season]))
    state_store.reset()
    ctrl = AutonomousController()
    ctrl.env = env
    provider = {"scheduled": ScheduledProvider, "forecast": ForecastProvider, "llm": BuildingAIAgent}.get(mode)
    provider = provider() if provider else None
    if mode == "llm" and not await provider.check_availability(force=True):
        return {"mode": mode, "season": season, "seed": seed, "status": "unavailable", "model": settings.LLM_MODEL}
    occupied = comfortable = 0
    discomfort_degree_hours = fan_energy = 0.0
    peak = 0.0
    sources = {}
    latencies = []
    for _ in range(steps):
        obs = await ctrl.step_simulation()
        peak = max(peak, obs.hvac_power_kw)
        fan_energy += obs.fan_power_kw * settings.TIMESTEP_MINUTES / 60
        if obs.occupancy >= 0.2:
            for z in obs.zones.values():
                occupied += 1
                comfortable += abs(z.pmv_score) <= 0.5
                discomfort_degree_hours += max(0, 20 - z.temperature, z.temperature - 26) * settings.TIMESTEP_MINUTES / 60
        if mode != "fixed":
            t0 = time.monotonic()
            decision = await provider.decide(obs) if provider else _rule_based_decision(obs)
            latencies.append(time.monotonic() - t0)
            sources[decision.controller_source] = sources.get(decision.controller_source, 0) + 1
            await ctrl._apply_decision(decision)
    return {"mode": mode, "season": season, "seed": seed, "status": "completed", "steps": steps, "days": steps * settings.TIMESTEP_MINUTES / 1440,
            "energy_kwh": obs.total_energy_kwh, "cost": obs.total_cost, "peak_kw": peak, "fan_energy_kwh": round(fan_energy, 3),
            "occupied_comfort_pct": round(100 * comfortable / occupied, 2) if occupied else None,
            "occupied_zone_samples": occupied, "discomfort_degree_hours": round(discomfort_degree_hours, 3),
            "decision_sources": sources, "mean_decision_seconds": statistics.mean(latencies) if latencies else 0,
            "p95_decision_seconds": sorted(latencies)[min(len(latencies)-1, int(len(latencies)*.95))] if latencies else 0}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--seeds", default="42,101,2024")
    parser.add_argument("--seasons", default=",".join(SEASONS))
    parser.add_argument("--modes", default="fixed,scheduled,rule_based,forecast")
    parser.add_argument("--output", default="docs/validation/seasonal_benchmark.json")
    args = parser.parse_args()
    if args.days < 1:
        parser.error("days must be positive")
    runs = []
    for season in args.seasons.split(","):
        if season not in SEASONS:
            parser.error(f"Unknown season: {season}")
        for seed in map(int, args.seeds.split(",")):
            for mode in args.modes.split(","):
                if mode not in ("fixed", "scheduled", "rule_based", "forecast", "llm"):
                    parser.error(f"Unknown mode: {mode}")
                result = await scenario(mode, season, seed, int(args.days * 1440 / settings.TIMESTEP_MINUTES))
                runs.append(result)
                print(json.dumps(result), flush=True)
                target = Path(args.output)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps({"model": "synthetic thermal model with fan/ventilation", "currency": settings.TARIFF_CURRENCY, "run_order": "step then decide for next step", "runs": runs}, indent=2), encoding="utf-8")
    lines = ["# Seasonal benchmark", "", "Synthetic weather; identical per-season seeds and initial conditions. Comfort includes occupied samples only. Fan energy and configurable time-of-use cost are included. LLM source counts identify fallback explicitly.", "", "| Season | Seed | Controller | kWh | Cost | Occupied comfort % | Peak kW |", "|---|---|---|---|---|---|---|"]
    for r in runs:
        lines.append(f"| {r['season']} | {r['seed']} | {r['mode']} | {r.get('energy_kwh', 'unavailable')} | {r.get('cost', '—')} | {r.get('occupied_comfort_pct', '—')} | {r.get('peak_kw', '—')} |")
    target.with_suffix(".md").write_text("\n".join(lines)+"\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
