export function baselinePower(entry) {
  return entry.baseline_power_kw ?? null;
}

export function zoneTemperature(entry, zone) {
  const measured = entry.zones?.[zone]?.temperature;
  return Number.isFinite(measured) ? measured : null;
}

export function appendTelemetry(history, entry, limit = 200) {
  const previous = history[history.length - 1];
  const next = previous?.sim_time === entry.sim_time
    ? [...history.slice(0, -1), entry]
    : [...history, entry];
  return next.slice(-limit);
}

export function formatAppliedSetpoints(applied = {}) {
  return Object.entries(applied)
    .map(([zone, sp]) => `${zone}: Cool ${sp.cooling}°C / Heat ${sp.heating}°C`)
    .join('; ');
}
