"""Deterministic forecast inputs and a configurable time-of-use tariff."""
import math
from datetime import timedelta

from config.settings import settings


def electricity_rate(dt):
    start, end = settings.TARIFF_PEAK_START, settings.TARIFF_PEAK_END
    peak = start <= dt.hour < end if start < end else dt.hour >= start or dt.hour < end
    return settings.TARIFF_PEAK if dt.weekday() < 5 and peak else settings.TARIFF_OFFPEAK


def forecast_conditions(dt, occupancy_schedule, hours=6):
    """Synthetic expected weather and scheduled occupancy; no random generator consumption."""
    points = []
    for offset in range(1, hours + 1):
        future = dt + timedelta(hours=offset)
        seasonal = 12 * math.sin(2 * math.pi * (future.timetuple().tm_yday - 80) / 365)
        outdoor = 10 + seasonal + 5 * math.sin(2 * math.pi * (future.hour + future.minute / 60 - 6) / 24)
        points.append({"time": future.isoformat(), "outdoor_temp": round(outdoor, 2), "occupancy": round(occupancy_schedule.get(future), 3), "electricity_rate": electricity_rate(future)})
    return points
