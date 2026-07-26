import React, { useEffect, useState } from 'react';
import { Leaf, TreePine, Car } from 'lucide-react';

export default function SavingsCounter({ savingsPct = 0, co2Saved = 0, totalEnergy = 0, baselineEnergy = 0 }) {
  const [displayValue, setDisplayValue] = useState(0);

  useEffect(() => {
    let startTimestamp = null;
    const duration = 1000;
    const initialValue = displayValue;

    const step = (timestamp) => {
      if (!startTimestamp) startTimestamp = timestamp;
      const progress = Math.min((timestamp - startTimestamp) / duration, 1);
      
      const ease = 1 - Math.pow(1 - progress, 4);
      
      setDisplayValue(initialValue + (savingsPct - initialValue) * ease);
      
      if (progress < 1) {
        window.requestAnimationFrame(step);
      }
    };
    
    window.requestAnimationFrame(step);
  }, [savingsPct]);

  const treesPlanted = (co2Saved / 21).toFixed(1);
  const milesAvoided = (co2Saved / 0.4).toFixed(0);

  return (
    <div className="glass-card p-6 relative overflow-hidden bg-gradient-to-br from-[#111827] to-[#1a2f1c]">
      <div className="absolute -right-10 -bottom-10 opacity-10">
        <Leaf size={150} />
      </div>
      
      <h3 className="text-sm font-medium text-gray-400 mb-4 flex items-center gap-2">
        <Leaf size={16} className="text-green-500" /> Sustainability Impact
      </h3>
      
      <div className="mb-6">
        <div className="text-5xl font-bold text-green-400 tracking-tighter">
          {displayValue.toFixed(1)}<span className="text-2xl text-green-500/50 ml-1">%</span>
        </div>
        <div className="text-sm text-gray-400 mt-1">Total Energy Reduction</div>
      </div>

      <div className="grid grid-cols-2 gap-4 mb-6 relative z-10">
        <div className="bg-black/20 rounded-lg p-3 border border-white/5">
          <div className="flex items-center gap-2 text-green-500 mb-1">
            <TreePine size={14} /> <span className="text-xs uppercase font-bold tracking-wider">Trees Eq.</span>
          </div>
          <div className="text-xl font-medium text-white">{treesPlanted}</div>
        </div>
        <div className="bg-black/20 rounded-lg p-3 border border-white/5">
          <div className="flex items-center gap-2 text-blue-400 mb-1">
            <Car size={14} /> <span className="text-xs uppercase font-bold tracking-wider">Miles Avoided</span>
          </div>
          <div className="text-xl font-medium text-white">{milesAvoided}</div>
        </div>
      </div>

      <div className="relative z-10">
        <div className="flex justify-between text-xs text-gray-400 mb-2">
          <span>Current: <strong className="text-white">{totalEnergy.toFixed(1)} kWh</strong></span>
          <span>Baseline: <strong className="text-white">{baselineEnergy.toFixed(1)} kWh</strong></span>
        </div>
        <div className="h-3 bg-gray-700 rounded-full overflow-hidden flex">
          <div className="h-full bg-green-500" style={{ width: `${(totalEnergy / Math.max(baselineEnergy, 1)) * 100}%` }} title="Actual Energy"></div>
          <div className="h-full bg-gray-500/50" style={{ width: `${Math.max(0, 100 - (totalEnergy / Math.max(baselineEnergy, 1)) * 100)}%` }} title="Savings"></div>
        </div>
      </div>
    </div>
  );
}
