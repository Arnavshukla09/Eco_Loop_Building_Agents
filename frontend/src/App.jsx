import React, { useState, useEffect } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import MetricCard from './components/MetricCard';
import AIDecisionPanel from './components/AIDecisionPanel';
import TemperatureChart from './components/TemperatureChart';
import EnergyChart from './components/EnergyChart';
import ComfortGauge from './components/ComfortGauge';
import ZoneGrid from './components/ZoneGrid';
import SavingsCounter from './components/SavingsCounter';
import SetpointControl from './components/SetpointControl';
import { Building2, Zap, Percent, TreePine, Thermometer, WifiOff, Wifi, Clock, Bot, Cpu, AlertTriangle } from 'lucide-react';
import { format } from 'date-fns';

export default function App() {
  const { data, isConnected, isStale, lastUpdate } = useWebSocket();
  const [history, setHistory] = useState([]);

  useEffect(() => {
    fetch('/api/history?limit=100')
      .then(res => res.json())
      .then(d => {
        if (d && d.entries) {
          setHistory(d.entries);
        }
      })
      .catch(err => console.error("Failed to fetch history:", err));
  }, []);

  useEffect(() => {
    if (data && data.building) {
      setHistory(prev => {
        const newEntry = {
          sim_time: data.building.simulation_time,
          wall_time: data.timestamp,
          avg_temp: data.building.avg_temperature,
          hvac_power_kw: data.building.hvac_power_kw,
          total_energy_kwh: data.building.total_energy_kwh,
          comfort_score: data.metrics?.comfort_score || 0,
          energy_savings_pct: data.metrics?.energy_savings_pct || 0,
          outdoor_temp: data.building.outdoor_temp,
          occupancy: data.building.occupancy,
          zones: data.building.zones
        };
        const next = [...prev, newEntry];
        if (next.length > 200) return next.slice(-200);
        return next;
      });
    }
  }, [data]);

  if (!data) {
    return (
      <div className="min-h-screen bg-brand-navy flex flex-col items-center justify-center text-white">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-brand-orange mb-4"></div>
        <h2 className="text-xl font-semibold">Connecting to Building Agent...</h2>
        <p className="text-gray-500 mt-2">Waiting for live building telemetry...</p>
      </div>
    );
  }

  const { building, ai_decision, metrics, simulation_mode } = data;
  const isLLMActive = ai_decision?.controller_source === 'llm';

  return (
    <div className="min-h-screen bg-brand-navy text-gray-200 p-4 md:p-6 lg:p-8 font-sans selection:bg-brand-orange/30">
      
      {/* Telemetry Stall or Disconnect Alert Banner */}
      {!isConnected && (
        <div className="mb-4 p-3 bg-red-500/20 border border-red-500/40 rounded-lg text-red-200 text-xs flex items-center justify-between">
          <span className="flex items-center gap-2">
            <WifiOff size={16} className="text-red-400" />
            <strong>Disconnected from building server:</strong> Retrying connection in background...
          </span>
          <span className="font-mono text-[11px] text-red-300">Offline</span>
        </div>
      )}
      {isConnected && isStale && (
        <div className="mb-4 p-2.5 bg-yellow-500/10 border border-yellow-500/30 rounded-lg text-yellow-200 text-xs flex items-center gap-2">
          <AlertTriangle size={15} className="text-yellow-400" />
          <span>Telemetry update delay: Displaying last received sensor state (last heartbeat: {lastUpdate ? format(lastUpdate, 'HH:mm:ss') : '--'}).</span>
        </div>
      )}

      <header className="flex flex-col md:flex-row justify-between items-start md:items-center mb-8 gap-4">
        <div className="flex items-center gap-3">
          <div className="bg-brand-orange p-2 rounded-lg text-white shadow-[0_0_15px_rgba(255,107,26,0.5)]">
            <Building2 size={28} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-2xl font-bold text-white tracking-tight">Eco-Loop Building Agent</h1>
              <span className={`text-[10px] uppercase font-bold px-2 py-0.5 rounded flex items-center gap-1 ${
                isLLMActive 
                  ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30' 
                  : 'bg-blue-500/20 text-blue-300 border border-blue-500/30'
              }`}>
                {isLLMActive ? <Bot size={11} /> : <Cpu size={11} />}
                {isLLMActive ? 'Qwen2.5 LLM' : 'Rule-Based Fallback'}
              </span>
            </div>
            <p className="text-sm text-gray-400">Autonomous Physical AI & HVAC Optimization</p>
          </div>
        </div>
        
        <div className="flex items-center gap-4 bg-brand-card/50 p-2 rounded-lg border border-white/5 backdrop-blur-sm">
          <div className="flex items-center gap-2 px-3 border-r border-white/10">
            <Clock size={16} className="text-gray-400" />
            <div className="text-sm">
              <div className="text-gray-500 text-[10px] uppercase font-bold">Sim Time</div>
              <div className="font-mono">{format(new Date(building.simulation_time), 'MMM dd, HH:mm')}</div>
            </div>
          </div>
          
          <div className="flex items-center gap-2 px-3">
            {isConnected ? (
              <Wifi size={16} className="text-green-500 animate-pulse" />
            ) : (
              <WifiOff size={16} className="text-red-500" />
            )}
            <div className="text-sm">
              <div className="text-gray-500 text-[10px] uppercase font-bold">Status</div>
              <div className={isConnected ? 'text-green-400' : 'text-red-400'}>
                {isConnected ? 'Live' : 'Disconnected'}
              </div>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-[1600px] mx-auto space-y-6">
        
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
          <MetricCard 
            title="Avg Temperature" 
            value={building.avg_temperature.toFixed(1)} 
            unit="°C" 
            icon={Thermometer} 
            color="#3B82F6"
            subtitle={`Outdoor: ${building.outdoor_temp.toFixed(1)}°C`}
          />
          <MetricCard 
            title="HVAC Power" 
            value={building.hvac_power_kw.toFixed(1)} 
            unit="kW" 
            icon={Zap} 
            color="#FF6B1A"
            subtitle={`Peak: ${metrics.peak_demand_kw?.toFixed(1) || '--'} kW`}
          />
          <MetricCard 
            title="Comfort Score" 
            value={(metrics.comfort_score * 100).toFixed(0)} 
            unit="%" 
            icon={Percent} 
            color="#22C55E"
            subtitle="ASHRAE 55 Compliant"
          />
          <MetricCard 
            title="Energy Savings" 
            value={metrics.energy_savings_pct.toFixed(1)} 
            unit="%" 
            icon={Zap} 
            color="#10B981"
            trend={{ dir: 'up', val: metrics.energy_savings_pct.toFixed(1) }}
          />
          <MetricCard 
            title="CO₂ Saved" 
            value={metrics.co2_saved_kg.toFixed(1)} 
            unit="kg" 
            icon={TreePine} 
            color="#059669"
            subtitle="Since start"
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <AIDecisionPanel decision={ai_decision} isConnected={isConnected} />
          </div>
          <div className="lg:col-span-1">
            <ComfortGauge 
              comfortScore={metrics.comfort_score} 
              avgPmv={building.avg_pmv} 
              avgPpd={building.avg_ppd} 
            />
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <TemperatureChart history={history} zones={building.zones} />
          <EnergyChart history={history} />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <SetpointControl 
              currentSetpoints={building.zones} 
              isConnected={isConnected} 
              onResetSuccess={() => setHistory([])} 
            />
          </div>
          <div className="lg:col-span-1">
            <SavingsCounter 
              savingsPct={metrics.energy_savings_pct}
              co2Saved={metrics.co2_saved_kg}
              totalEnergy={metrics.current_energy_kwh}
              baselineEnergy={metrics.baseline_energy_kwh}
            />
          </div>
        </div>

        <div className="w-full">
          <ZoneGrid zones={building.zones} />
        </div>
      </main>

      <footer className="mt-12 pt-4 border-t border-white/10 flex flex-wrap justify-between items-center text-xs text-gray-500 gap-4">
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1"><Bot size={14} /> Agent v1.0.0</span>
          {simulation_mode && <span className="bg-brand-orange/20 text-brand-orange px-2 py-0.5 rounded">SIMULATION MODE</span>}
        </div>
        <div>
          Last update: {lastUpdate ? format(lastUpdate, 'HH:mm:ss') : '--:--:--'}
        </div>
      </footer>
    </div>
  );
}
