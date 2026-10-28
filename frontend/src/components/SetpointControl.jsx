import React, { useState } from 'react';
import { Sliders, RotateCcw, CheckCircle2, AlertTriangle, Key, ShieldCheck } from 'lucide-react';

const ZONES = ['Core', 'Perimeter_N', 'Perimeter_S', 'Perimeter_E', 'Perimeter_W'];

export default function SetpointControl({ currentSetpoints, isConnected, onResetSuccess }) {
  const [selectedZone, setSelectedZone] = useState('ALL');
  const [cooling, setCooling] = useState(24.0);
  const [heating, setHeating] = useState(20.0);
  const [apiKey, setApiKey] = useState(() => localStorage.getItem('eco_api_key') || '');
  const [showKeyField, setShowKeyField] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isResetting, setIsResetting] = useState(false);
  const [feedback, setFeedback] = useState(null); // { type: 'success' | 'error', message: string }

  // Client-side deadband calculation: cooling >= heating + 1.5
  const deadband = cooling - heating;
  const isDeadbandValid = deadband >= 1.5;

  const handleHeatingChange = (val) => {
    const newHeat = parseFloat(val);
    setHeating(newHeat);
    if (cooling < newHeat + 1.5) {
      setCooling(Math.min(30.0, parseFloat((newHeat + 1.5).toFixed(1))));
    }
  };

  const handleCoolingChange = (val) => {
    const newCool = parseFloat(val);
    setCooling(newCool);
    if (newCool < heating + 1.5) {
      setHeating(Math.max(16.0, parseFloat((newCool - 1.5).toFixed(1))));
    }
  };

  const handleApiKeyChange = (e) => {
    const key = e.target.value;
    setApiKey(key);
    localStorage.setItem('eco_api_key', key);
  };

  const applySetpoints = async (e) => {
    e.preventDefault();
    if (!isDeadbandValid) return;
    setIsSubmitting(true);
    setFeedback(null);

    const payload = {
      zone: selectedZone === 'ALL' ? null : selectedZone,
      cooling: cooling,
      heating: heating,
    };

    const headers = { 'Content-Type': 'application/json' };
    if (apiKey.trim()) {
      headers['Authorization'] = `Bearer ${apiKey.trim()}`;
    }

    try {
      const res = await fetch('/api/setpoint', {
        method: 'POST',
        headers,
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (res.ok && data.success) {
        setFeedback({
          type: 'success',
          message: `${data.message} (Cool: ${data.cooling_c}°C, Heat: ${data.heating_c}°C)`,
        });
      } else {
        setFeedback({
          type: 'error',
          message: data.detail || data.message || 'Failed to update setpoints.',
        });
      }
    } catch (err) {
      setFeedback({
        type: 'error',
        message: `Network error: ${err.message}`,
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const resetSimulation = async () => {
    if (!window.confirm('Reset building simulation and reference baseline back to step 0?')) {
      return;
    }
    setIsResetting(true);
    setFeedback(null);

    const headers = {};
    if (apiKey.trim()) {
      headers['Authorization'] = `Bearer ${apiKey.trim()}`;
    }

    try {
      const res = await fetch('/api/simulation/reset', {
        method: 'POST',
        headers,
      });
      const data = await res.json();
      if (res.ok && data.success) {
        setFeedback({
          type: 'success',
          message: 'Simulation and reference baseline reset to initial state.',
        });
        if (onResetSuccess) onResetSuccess();
      } else {
        setFeedback({
          type: 'error',
          message: data.detail || 'Failed to reset simulation.',
        });
      }
    } catch (err) {
      setFeedback({ type: 'error', message: `Reset error: ${err.message}` });
    } finally {
      setIsResetting(false);
    }
  };

  return (
    <div className="bg-brand-card/80 border border-white/10 rounded-xl p-5 backdrop-blur-md shadow-xl text-gray-200">
      <div className="flex items-center justify-between mb-4 pb-3 border-b border-white/10">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-brand-orange/20 text-brand-orange">
            <Sliders size={18} />
          </div>
          <div>
            <h3 className="font-semibold text-white text-base">HVAC Thermostat Controls</h3>
            <p className="text-xs text-gray-400">Manual override with validated 1.5°C safety deadband</p>
          </div>
        </div>
        <button
          onClick={() => setShowKeyField(!showKeyField)}
          className={`flex items-center gap-1 text-xs px-2.5 py-1 rounded border transition-colors ${
            apiKey.trim()
              ? 'border-green-500/30 text-green-400 bg-green-500/10'
              : 'border-white/10 text-gray-400 hover:text-gray-200'
          }`}
          title="Configure API Token for protected endpoints"
        >
          {apiKey.trim() ? <ShieldCheck size={13} /> : <Key size={13} />}
          <span>{apiKey.trim() ? 'Key Set' : 'Auth'}</span>
        </button>
      </div>

      {showKeyField && (
        <div className="mb-4 p-3 bg-black/40 border border-white/5 rounded-lg text-xs space-y-1">
          <label className="text-gray-400 block font-medium">Authorization Bearer Token (Optional in Dev):</label>
          <input
            type="password"
            value={apiKey}
            onChange={handleApiKeyChange}
            placeholder="Enter API_KEY if enabled on backend"
            className="w-full bg-[#0A0E1A] border border-white/10 rounded px-2.5 py-1.5 text-white font-mono text-xs focus:outline-none focus:border-brand-orange"
          />
        </div>
      )}

      <form onSubmit={applySetpoints} className="space-y-4">
        <div>
          <label className="text-xs font-semibold text-gray-400 block mb-1 uppercase tracking-wider">
            Target Zone
          </label>
          <select
            value={selectedZone}
            onChange={(e) => setSelectedZone(e.target.value)}
            className="w-full bg-[#0A0E1A] border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-brand-orange"
          >
            <option value="ALL">All Zones (Synchronized)</option>
            {ZONES.map((z) => (
              <option key={z} value={z}>{z}</option>
            ))}
          </select>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="bg-[#0A0E1A]/60 p-3 rounded-lg border border-white/5">
            <div className="flex justify-between items-center mb-1">
              <span className="text-xs text-blue-400 font-medium">Heating Setpoint</span>
              <span className="font-mono text-sm font-bold text-blue-300">{heating.toFixed(1)}°C</span>
            </div>
            <input
              type="range"
              min="16.0"
              max="22.0"
              step="0.5"
              value={heating}
              onChange={(e) => handleHeatingChange(e.target.value)}
              className="w-full accent-blue-500 cursor-pointer"
            />
            <div className="flex justify-between text-[10px] text-gray-500 mt-0.5">
              <span>16.0°C (Min)</span>
              <span>22.0°C (Max)</span>
            </div>
          </div>

          <div className="bg-[#0A0E1A]/60 p-3 rounded-lg border border-white/5">
            <div className="flex justify-between items-center mb-1">
              <span className="text-xs text-brand-orange font-medium">Cooling Setpoint</span>
              <span className="font-mono text-sm font-bold text-orange-300">{cooling.toFixed(1)}°C</span>
            </div>
            <input
              type="range"
              min="20.0"
              max="30.0"
              step="0.5"
              value={cooling}
              onChange={(e) => handleCoolingChange(e.target.value)}
              className="w-full accent-brand-orange cursor-pointer"
            />
            <div className="flex justify-between text-[10px] text-gray-500 mt-0.5">
              <span>20.0°C (Min)</span>
              <span>30.0°C (Max)</span>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between text-xs px-1 text-gray-400">
          <span>
            Active Gap (Deadband):{' '}
            <strong className={isDeadbandValid ? 'text-green-400 font-mono' : 'text-red-400 font-mono'}>
              {deadband.toFixed(1)}°C
            </strong>{' '}
            (min 1.5°C required)
          </span>
        </div>

        {feedback && (
          <div
            className={`p-3 rounded-lg text-xs flex items-center gap-2 ${
              feedback.type === 'success'
                ? 'bg-green-500/10 border border-green-500/30 text-green-300'
                : 'bg-red-500/10 border border-red-500/30 text-red-300'
            }`}
          >
            {feedback.type === 'success' ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
            <span>{feedback.message}</span>
          </div>
        )}

        <div className="flex items-center gap-3 pt-1">
          <button
            type="submit"
            disabled={isSubmitting || !isConnected}
            className="flex-1 bg-brand-orange hover:bg-orange-600 disabled:opacity-50 text-white font-medium py-2 px-4 rounded-lg text-sm transition-all shadow-lg shadow-brand-orange/20"
          >
            {isSubmitting ? 'Applying Setpoints...' : 'Apply Setpoint Override'}
          </button>

          <button
            type="button"
            onClick={resetSimulation}
            disabled={isResetting || !isConnected}
            className="flex items-center gap-1.5 px-3 py-2 bg-white/5 hover:bg-white/10 text-gray-300 rounded-lg text-xs font-medium border border-white/10 transition-colors"
            title="Reset simulation and reference baseline back to step 0"
          >
            <RotateCcw size={14} className={isResetting ? 'animate-spin' : ''} />
            <span>Reset</span>
          </button>
        </div>
      </form>
    </div>
  );
}
