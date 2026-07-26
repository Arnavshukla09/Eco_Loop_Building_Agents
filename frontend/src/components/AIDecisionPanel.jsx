import React from 'react';
import { Cpu, Wind, ThermometerSnowflake, Flame } from 'lucide-react';

export default function AIDecisionPanel({ decision, isConnected }) {
  if (!decision) {
    return (
      <div className="glass-card p-6 h-full border-l-4 border-l-gray-600 flex items-center justify-center">
        <div className="text-gray-500 flex flex-col items-center gap-2">
          <Cpu size={32} className="opacity-50" />
          <p>Waiting for AI Agent data...</p>
        </div>
      </div>
    );
  }

  const { zone_setpoints, fan_speed, energy_mode, reasoning, confidence, estimated_savings_pct } = decision;

  const modeColors = {
    eco: 'bg-green-500/20 text-green-400 border-green-500/30',
    balanced: 'bg-brand-orange/20 text-brand-orange border-brand-orange/30',
    comfort: 'bg-blue-500/20 text-blue-400 border-blue-500/30'
  };

  return (
    <div className="glass-card p-6 h-full border-l-4 border-l-brand-orange relative overflow-hidden flex flex-col">
      <div className="flex justify-between items-start mb-6">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-brand-orange/20 rounded-lg">
            <Cpu className="text-brand-orange" size={24} />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-white">AI Agent Decision</h2>
            <div className="flex items-center gap-2 text-sm mt-1">
              <span className={`px-2 py-0.5 rounded-full border text-xs font-medium uppercase tracking-wider ${modeColors[energy_mode] || modeColors.balanced}`}>
                {energy_mode} MODE
              </span>
              <span className="text-gray-400">Confidence: {(confidence * 100).toFixed(0)}%</span>
            </div>
          </div>
        </div>
        
        <div className="text-right">
          <div className="text-xs text-gray-400 mb-1">Est. Savings</div>
          <div className="text-xl font-bold text-green-400">+{estimated_savings_pct?.toFixed(1)}%</div>
        </div>
      </div>

      <div className="bg-brand-navy/50 p-4 rounded-lg border border-white/5 mb-6">
        <p className="text-sm text-gray-300 italic">"{reasoning}"</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 flex-grow">
        <div>
          <h3 className="text-sm font-medium text-gray-400 mb-3 flex items-center gap-2">
            <Wind size={16} /> Fan Speed
          </h3>
          <div className="flex items-end gap-1 h-8">
            <div className={`w-1/3 rounded-t-sm transition-all duration-500 ${fan_speed === 'low' || fan_speed === 'medium' || fan_speed === 'high' ? 'bg-brand-orange h-4' : 'bg-gray-700 h-2'}`}></div>
            <div className={`w-1/3 rounded-t-sm transition-all duration-500 ${fan_speed === 'medium' || fan_speed === 'high' ? 'bg-brand-orange h-6' : 'bg-gray-700 h-2'}`}></div>
            <div className={`w-1/3 rounded-t-sm transition-all duration-500 ${fan_speed === 'high' ? 'bg-brand-orange h-8' : 'bg-gray-700 h-2'}`}></div>
          </div>
          <div className="text-xs text-center mt-1 text-gray-400 uppercase tracking-widest">{fan_speed}</div>
        </div>
        
        <div>
          <h3 className="text-sm font-medium text-gray-400 mb-3">Zone Setpoints</h3>
          <div className="space-y-2 font-mono text-xs max-h-32 overflow-y-auto pr-2 custom-scrollbar">
            {Object.entries(zone_setpoints || {}).map(([zone, sp]) => (
              <div key={zone} className="flex justify-between items-center py-1 border-b border-white/5">
                <span className="text-gray-300 truncate w-24" title={zone}>{zone.replace('Perimeter_', 'P_')}</span>
                <div className="flex gap-3">
                  <span className="text-blue-400 flex items-center gap-1" title="Cooling Setpoint">
                    <ThermometerSnowflake size={12}/> {sp.cooling.toFixed(1)}
                  </span>
                  <span className="text-red-400 flex items-center gap-1" title="Heating Setpoint">
                    <Flame size={12}/> {sp.heating.toFixed(1)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
      
      <div className="mt-4 text-xs text-gray-500 text-right">
        Live optimization active • {isConnected ? 'Connected' : 'Disconnected'}
      </div>
    </div>
  );
}
