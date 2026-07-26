import React from 'react';

export default function ComfortGauge({ comfortScore = 0, avgPmv = 0, avgPpd = 0 }) {
  const percentage = Math.round(comfortScore * 100);
  
  let color = '#22C55E';
  if (percentage < 60) color = '#EF4444';
  else if (percentage < 80) color = '#F59E0B';

  const radius = 60;
  const circumference = 2 * Math.PI * radius;
  const arcLength = circumference * 0.75;
  const strokeDashoffset = arcLength - (percentage / 100) * arcLength;

  const pmvPercent = ((avgPmv + 3) / 6) * 100;

  return (
    <div className="glass-card p-6 h-full flex flex-col items-center justify-center relative">
      <h3 className="text-sm font-medium text-gray-400 absolute top-4 left-4">Occupant Comfort</h3>
      
      <div className={`absolute top-4 right-4 px-2 py-1 rounded text-[10px] font-bold border ${percentage >= 80 ? 'border-green-500/50 text-green-400 bg-green-500/10' : 'border-gray-500/50 text-gray-400 bg-gray-500/10'}`}>
        ASHRAE 55
      </div>

      <div className="relative w-40 h-40 mt-4 flex items-center justify-center">
        <svg className="absolute inset-0 w-full h-full transform -rotate-90">
          <circle
            cx="80"
            cy="80"
            r={radius}
            fill="none"
            stroke="rgba(255,255,255,0.05)"
            strokeWidth="12"
            strokeDasharray={`${arcLength} ${circumference}`}
            strokeLinecap="round"
          />
        </svg>
        
        <svg className="absolute inset-0 w-full h-full transform -rotate-90">
          <circle
            cx="80"
            cy="80"
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth="12"
            strokeDasharray={`${arcLength} ${circumference}`}
            strokeDashoffset={strokeDashoffset}
            strokeLinecap="round"
            style={{ transition: 'stroke-dashoffset 1s ease-out, stroke 0.5s ease' }}
          />
        </svg>

        <div className="flex flex-col items-center">
          <span className="text-4xl font-bold tracking-tighter" style={{ color }}>
            {percentage}<span className="text-lg text-gray-400 ml-1">%</span>
          </span>
          <span className="text-xs text-gray-500 uppercase tracking-widest mt-1">Score</span>
        </div>
      </div>

      <div className="w-full mt-6 space-y-4">
        <div>
          <div className="flex justify-between text-[10px] text-gray-500 mb-1">
            <span>Cold (-3)</span>
            <span>PMV</span>
            <span>Hot (+3)</span>
          </div>
          <div className="h-2 bg-gradient-to-r from-blue-500 via-green-500 to-red-500 rounded-full relative">
            <div 
              className="absolute top-1/2 -translate-y-1/2 w-3 h-4 bg-white shadow-sm border border-gray-300 rounded-[2px]"
              style={{ left: `calc(${Math.max(0, Math.min(100, pmvPercent))}% - 6px)`, transition: 'left 0.5s ease-out' }}
            />
          </div>
          <div className="text-center text-xs mt-1 font-mono text-gray-300">
            {avgPmv > 0 ? '+' : ''}{avgPmv.toFixed(2)}
          </div>
        </div>
        
        <div className="flex justify-between items-center border-t border-white/5 pt-3">
          <span className="text-xs text-gray-400">Predicted Dissatisfied (PPD)</span>
          <span className="text-sm font-medium text-white">{avgPpd.toFixed(1)}%</span>
        </div>
      </div>
    </div>
  );
}
