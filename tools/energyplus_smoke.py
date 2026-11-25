"""Run the real EnergyPlus adapter and verify a thermostat update."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.settings import settings
from backend.energyplus_runner import EnergyPlusBuildingEnvironment


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True)
    parser.add_argument("--weather", required=True)
    parser.add_argument("--output", default="docs/validation/energyplus_smoke.json")
    args = parser.parse_args()
    settings.ENERGYPLUS_PATH = str(Path(args.engine).resolve())
    settings.WEATHER_FILE = str(Path(args.weather).resolve())
    env = EnergyPlusBuildingEnvironment()
    try:
        await env.initialize()
        first = await env.step()
        if not await env.set_setpoint("Core", 26.0, 18.0):
            raise RuntimeError("EnergyPlus rejected the Core thermostat update")
        second = await env.step()
        if second.timestep <= first.timestep:
            raise RuntimeError("EnergyPlus did not advance after thermostat update")
        elapsed_minutes = (second.simulation_time - first.simulation_time).total_seconds() / 60
        if abs(elapsed_minutes - settings.TIMESTEP_MINUTES) > 0.001:
            raise RuntimeError(f"EnergyPlus zone clock advanced by {elapsed_minutes} minutes")
        core = second.zones["Core"]
        if core.setpoint_cooling != 26.0 or core.setpoint_heating != 18.0:
            raise RuntimeError(f"EnergyPlus thermostat feedback did not match: {core}")
        result = {"status": "passed", "engine": "EnergyPlus 24.1", "zones": list(second.zones), "steps": second.timestep, "setpoint_actuation": second.zones["Core"].model_dump(), "observation": second.model_dump(mode="json")}
    finally:
        await env.close()
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
