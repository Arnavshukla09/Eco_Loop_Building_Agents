"""Read explicitly mapped building telemetry once; never writes device values."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.hardware import ModbusMonitor, ModbusPoint, BACnetMonitor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mapping", help="JSON device point mapping")
    args = parser.parse_args()
    config = json.loads(Path(args.mapping).read_text())
    if config["protocol"] == "modbus":
        result = ModbusMonitor(config["host"], [ModbusPoint(**p) for p in config["points"]], port=config.get("port", 502), device_id=config.get("device_id", 1)).sample()
    elif config["protocol"] == "bacnet":
        async def read():
            from bacpypes3.app import Application
            from bacpypes3.argparse import SimpleArgumentParser
            arguments = SimpleArgumentParser().parse_args(["--address", config["local_address"], "--instance", str(config["local_instance"])])
            app = Application.from_args(arguments)
            try:
                return await asyncio.wait_for(BACnetMonitor(config["address"], config["points"]).sample(app), timeout=10)
            finally:
                app.close()
        result = asyncio.run(read())
    else:
        parser.error("protocol must be modbus or bacnet")
    print(json.dumps({"mode": "monitor_only", "values": result}, indent=2))


if __name__ == "__main__":
    main()
