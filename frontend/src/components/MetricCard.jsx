import React from 'react';
import { Building2, Activity, Zap, Percent, TreePine, AlertTriangle, Wind, Thermometer, Battery, Leaf } from 'lucide-react';

export default function MetricCard({ title, value, unit, icon: Icon, color, subtitle, trend }) {
  return (
    <div className="glass-card p-4 hover:shadow-[0_0_15px_rgba(255,107,26,0.15)] group relative overflow-hidden">
      <div className="absolute top-0 right-0 w-24 h-24 bg-gradient-to-br opacity-5 rounded-bl-full transition-transform group-hover:scale-110" style={{ backgroundImage: `linear-gradient(to bottom right, ${color}, transparent)` }} />
      
      <div className="flex justify-between items-start mb-2 relative z-10">
        <h3 className="text-gray-400 font-medium text-sm flex items-center gap-2">
          {Icon && <Icon size={16} style={{ color }} />}
          {title}
        </h3>
        {trend && (
          <span className={`text-xs px-2 py-1 rounded-full ${
            trend.dir === 'up' ? 'bg-green-500/10 text-green-400' : 
            trend.dir === 'down' ? 'bg-red-500/10 text-red-400' : 
            'bg-gray-500/10 text-gray-400'
          }`}>
            {trend.dir === 'up' ? '↑' : trend.dir === 'down' ? '↓' : '-'} {Math.abs(trend.val)}%
          </span>
        )}
      </div>
      
      <div className="flex items-baseline gap-1 mt-2 relative z-10">
        <span className="text-3xl font-bold text-white tracking-tight animate-[pulse_0.5s_ease-out]">{value}</span>
        {unit && <span className="text-gray-400 font-medium">{unit}</span>}
      </div>
      
      {subtitle && (
        <p className="text-xs text-gray-500 mt-2 relative z-10">{subtitle}</p>
      )}
    </div>
  );
}
