"""Explicit, monitor-only BACnet/IP and Modbus/TCP point readers.

These adapters never discover devices automatically and expose no write operation.
They return observations for commissioning, separate from simulated actuation.
"""
from dataclasses import dataclass
import math
import struct


@dataclass(frozen=True)
class ModbusPoint:
    name: str
    address: int
    scale: float = 1.0
    offset: float = 0.0
    signed: bool = False
    register_type: str = "holding"

    def __post_init__(self):
        if self.register_type not in ("holding", "input"):
            raise ValueError("register_type must be 'holding' or 'input'")
        if not 0 <= self.address <= 65535:
            raise ValueError("Modbus register address must be between 0 and 65535")
        if not math.isfinite(self.scale) or not math.isfinite(self.offset):
            raise ValueError("Point scale and offset must be finite")


class ModbusMonitor:
    def __init__(self, host, points, port=502, device_id=1, timeout=3):
        self.host, self.port, self.points = host, port, points
        self.device_id, self.timeout = device_id, timeout

    def sample(self, client_factory=None):
        if client_factory is None:
            from pymodbus.client import ModbusTcpClient
            client_factory = ModbusTcpClient
        client = client_factory(self.host, port=self.port, timeout=self.timeout)
        values = {}
        try:
            if not client.connect():
                raise ConnectionError("Modbus connection failed")
            for point in self.points:
                reader = client.read_input_registers if point.register_type == "input" else client.read_holding_registers
                result = reader(point.address, count=1, device_id=self.device_id)
                if result.isError() or len(result.registers) != 1:
                    raise ValueError(f"Unable to read register for {point.name}")
                raw = result.registers[0]
                if point.signed:
                    raw = struct.unpack(">h", struct.pack(">H", raw))[0]
                value = raw * point.scale + point.offset
                if not math.isfinite(value):
                    raise ValueError(f"Nonfinite telemetry for {point.name}")
                values[point.name] = value
            return values
        finally:
            client.close()


class BACnetMonitor:
    def __init__(self, address, points):
        self.address, self.points = address, points

    async def sample(self, application):
        """Accept a bacpypes3 Application; read only configured object properties."""
        values = {}
        for name, point in self.points.items():
            value = await application.read_property(self.address, point["object"], point.get("property", "present-value"))
            numeric = float(value) * point.get("scale", 1.0) + point.get("offset", 0.0)
            if not math.isfinite(numeric):
                raise ValueError(f"Nonfinite telemetry for {name}")
            values[name] = numeric
        return values
