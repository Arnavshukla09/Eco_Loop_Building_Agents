import React, { useState } from 'react';
import { apiError, getApiToken } from '../utils/api';

export default function ControlStatus({ control = {}, building }) {
  const [error, setError] = useState('');
  const [releasing, setReleasing] = useState(false);
  const holds = Object.entries(control.overrides || {});
  const release = async () => {
    setReleasing(true);
    setError('');
    try {
      const key = getApiToken().trim();
      const res = await fetch('/api/override/release', { method: 'POST', headers: key ? { Authorization: `Bearer ${key}` } : {} });
      if (!res.ok) setError(apiError(await res.json(), 'Unable to release hold. Check your API key.'));
    } catch {
      setError('Unable to reach the building server. Try releasing the hold again.');
    } finally {
      setReleasing(false);
    }
  };
  return <section className="glass-card p-5 space-y-2" aria-label="Control status">
    <h2 className="font-semibold">Control status</h2>
    <p>Provider: {control.provider || 'Starting'} · Fan: {building.fan_speed} · Fan power: {building.fan_power_kw?.toFixed(2)} kW</p>
    <p>Ventilation: {building.ventilation_m3s?.toFixed(2)} m³/s · Rate: {building.electricity_rate?.toFixed(2)}/kWh · Cost: {building.total_cost?.toFixed(2)}</p>
    <p>{control.fan_actuation_supported ? 'Fan control active in simulation' : 'Fan recommendation is advisory for this environment'}</p>
    {error && <p role="alert">{error}</p>}
    {holds.length ? <><ul>{holds.map(([zone, hold]) => <li key={zone}>{zone}: held at {hold.cooling}/{hold.heating}°C until {hold.expires_at} simulation time</li>)}</ul><button disabled={releasing} onClick={release} className="text-orange-400">{releasing ? 'Releasing holds...' : 'Release all holds'}</button></> : <p>Automatic setpoint control · No manual holds</p>}
  </section>;
}
