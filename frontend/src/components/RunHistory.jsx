import React, { useEffect, useState } from 'react';
import EnergyChart from './EnergyChart';

export default function RunHistory() {
  const [runs, setRuns] = useState([]);
  const [selected, setSelected] = useState('');
  const [entries, setEntries] = useState([]);
  const [position, setPosition] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState('');
  const loadRuns = () => fetch('/api/simulation/runs')
    .then(r => { if (!r.ok) throw new Error(); return r.json(); })
    .then(d => { setRuns(d.runs || []); setError(''); })
    .catch(() => setError('Unable to load saved runs.'));
  useEffect(() => { loadRuns(); }, []);
  useEffect(() => {
    if (!selected) { setEntries([]); setPlaying(false); return; }
    const abort = new AbortController();
    setPlaying(false);
    setEntries([]);
    setPosition(0);
    fetch(`/api/simulation/runs/${encodeURIComponent(selected)}/history?limit=10000`, { signal: abort.signal })
      .then(r => { if (!r.ok) throw new Error(); return r.json(); })
      .then(d => { setEntries(d.entries || []); setPosition(0); setError(''); })
      .catch(e => { if (e.name !== 'AbortError') setError('Unable to load run history.'); });
    return () => abort.abort();
  }, [selected]);
  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => setPosition(p => { if (p >= entries.length - 1) { setPlaying(false); return p; } return p + 1; }), 400);
    return () => clearInterval(timer);
  }, [playing, entries.length]);
  const entry = entries[position];
  return <section className="glass-card p-5 space-y-4" aria-label="Saved simulation runs">
    <div className="flex justify-between"><h2 className="text-lg font-semibold">Run comparison and replay</h2><button onClick={loadRuns}>Refresh runs</button></div>
    {error && <p role="alert">{error}</p>}
    <div className="overflow-x-auto"><table className="w-full text-sm text-left"><thead><tr><th>Run</th><th>State</th><th>Energy (kWh)</th><th>Savings</th><th>Final comfort index</th></tr></thead>
      <tbody>{runs.map(run => <tr key={run.id} className="border-t border-white/10"><td><button className="text-orange-400 py-2" onClick={() => setSelected(run.id)}>{run.id}</button></td><td>{run.is_active ? 'Active' : 'Archived'}</td><td>{run.is_active ? 'In progress' : run.total_energy_kwh?.toFixed(2)}</td><td>{run.is_active ? '—' : `${run.final_savings_pct?.toFixed(1)}%`}</td><td>{run.is_active ? '—' : `${(run.final_comfort_score * 100).toFixed(0)}%`}</td></tr>)}</tbody></table></div>
    {selected && <div className="space-y-3">
      <p>Selected run: {selected} · {entries.length} saved readings</p>
      <a className="text-orange-400" href={`/api/simulation/runs/${encodeURIComponent(selected)}/export`}>Download CSV</a>
      {entries.length > 0 && <><div className="flex gap-3 items-center"><button onClick={() => setPlaying(p => !p)}>{playing ? 'Pause replay' : 'Play replay'}</button><input aria-label="Replay position" className="flex-1" type="range" min="0" max={entries.length - 1} value={position} onChange={e => setPosition(Number(e.target.value))} /></div>
        <p>{entry?.sim_time} · {entry?.avg_temp.toFixed(1)}°C · {entry?.total_energy_kwh.toFixed(2)} kWh · Cost {entry?.total_cost?.toFixed(2)}</p>
        <EnergyChart history={entries.slice(0, position + 1)} /></>}
    </div>}
  </section>;
}
