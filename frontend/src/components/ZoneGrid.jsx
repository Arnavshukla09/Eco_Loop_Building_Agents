import React, { useEffect, useState } from 'react';

export default function ZoneGrid({ zones }) {
  const [flashingCells, setFlashingCells] = useState({});

  useEffect(() => {
    if (zones) {
      setFlashingCells(Object.keys(zones).reduce((acc, zone) => ({ ...acc, [zone]: true }), {}));
      const timer = setTimeout(() => setFlashingCells({}), 500);
      return () => clearTimeout(timer);
    }
  }, [zones]);

  if (!zones || Object.keys(zones).length === 0) {
    return (
      <div className="glass-card p-4 overflow-x-auto min-h-[200px] flex items-center justify-center">
        <span className="text-gray-500">Waiting for zone data...</span>
      </div>
    );
  }

  const getStatus = (pmv, hasSensorFault) => {
    if (hasSensorFault) return { label: 'Sensor Fault', color: 'bg-red-500/30 text-red-300 border-red-500/50 animate-pulse' };
    const absPmv = Math.abs(pmv);
    if (absPmv < 0.5) return { label: 'Optimal', color: 'bg-green-500/20 text-green-400 border-green-500/30' };
    if (absPmv < 1.0) return { label: 'Acceptable', color: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30' };
    return { label: 'Warning', color: 'bg-red-500/20 text-red-400 border-red-500/30' };
  };

  const getTempColor = (temp, heatSp, coolSp) => {
    if (temp < heatSp) return 'text-blue-400';
    if (temp > coolSp) return 'text-red-400';
    return 'text-green-400';
  };

  return (
    <div className="glass-card overflow-hidden">
      <div className="p-4 border-b border-white/5 flex justify-between items-center bg-brand-navy/30">
        <h3 className="font-semibold text-white">Zone Overview</h3>
        <span className="text-xs text-gray-400">{Object.keys(zones).length} Zones Monitored</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-white/5 text-gray-400 text-xs uppercase tracking-wider">
              <th className="p-3 pl-4 font-medium">Zone</th>
              <th className="p-3 font-medium">Temp °C</th>
              <th className="p-3 font-medium text-blue-400">Cool SP</th>
              <th className="p-3 font-medium text-red-400">Heat SP</th>
              <th className="p-3 font-medium">PMV</th>
              <th className="p-3 font-medium">PPD %</th>
              <th className="p-3 font-medium">Humidity</th>
              <th className="p-3 pr-4 font-medium text-right">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5 text-sm">
            {Object.entries(zones).map(([name, data], idx) => {
              const status = getStatus(data.pmv_score, data.sensor_fault);
              const isFlashing = flashingCells[name];
              
              return (
                <tr key={name} className={`hover:bg-white/[0.02] transition-colors ${idx % 2 === 0 ? 'bg-transparent' : 'bg-black/10'}`}>
                  <td className="p-3 pl-4 font-medium text-gray-200">{name.replace('Perimeter_', 'P_')}</td>
                  <td className={`p-3 font-bold transition-colors duration-300 ${isFlashing ? 'text-white' : getTempColor(data.temperature, data.setpoint_heating, data.setpoint_cooling)}`}>
                    {data.temperature.toFixed(1)}
                    {data.sensor_fault && data.raw_temperature != null && (
                      <span className="block text-[10px] font-normal text-red-400 font-mono" title={`Raw sensor: ${data.raw_temperature}°C`}>
                        raw: {data.raw_temperature.toFixed(1)}
                      </span>
                    )}
                  </td>
                  <td className="p-3 text-gray-300 font-mono">{data.setpoint_cooling.toFixed(1)}</td>
                  <td className="p-3 text-gray-300 font-mono">{data.setpoint_heating.toFixed(1)}</td>
                  <td className="p-3 text-gray-300 font-mono">{data.pmv_score > 0 ? '+' : ''}{data.pmv_score.toFixed(2)}</td>
                  <td className="p-3 text-gray-300">{data.ppd_score.toFixed(1)}</td>
                  <td className="p-3 text-gray-400">{data.humidity.toFixed(1)}%</td>
                  <td className="p-3 pr-4 text-right">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] uppercase font-bold border ${status.color}`}>
                      {status.label}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
