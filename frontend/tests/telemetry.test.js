import test from 'node:test';
import assert from 'node:assert/strict';
import { baselinePower, zoneTemperature, appendTelemetry, formatAppliedSetpoints } from '../src/utils/telemetry.js';

test('zone history uses measured temperatures and leaves unavailable readings empty', () => {
  assert.equal(zoneTemperature({ zones: { Core: { temperature: 22.5 } } }, 'Core'), 22.5);
  assert.equal(zoneTemperature({ avg_temp: 22.5 }, 'Core'), null);
  assert.equal(zoneTemperature({ zones: { Core: { temperature: null } } }, 'Core'), null);
});

test('baseline uses measured instantaneous power even with zero savings', () => {
  assert.equal(baselinePower({ hvac_power_kw: 8, energy_savings_pct: 0, baseline_power_kw: 7 }), 7);
  assert.equal(baselinePower({ baseline_power_kw: 0 }), 0);
});

test('missing reference data leaves a gap rather than inventing savings', () => {
  assert.equal(baselinePower({ hvac_power_kw: 8, energy_savings_pct: 100 }), null);
});

test('heartbeat updates replace a timestep without duplicating history', () => {
  const first = { sim_time: '2024-01-01T08:00:00', baseline_power_kw: 0 };
  const latest = { ...first, baseline_power_kw: 2 };
  assert.deepEqual(appendTelemetry([first], latest), [latest]);
});

test('new simulation steps append and respect the history limit', () => {
  assert.deepEqual(appendTelemetry([{ sim_time: 'a' }, { sim_time: 'b' }], { sim_time: 'c' }, 2), [{ sim_time: 'b' }, { sim_time: 'c' }]);
});

test('control feedback displays actual values per zone', () => {
  assert.equal(formatAppliedSetpoints({ Core: { cooling: 26, heating: 18 }, Perimeter_N: { cooling: 25, heating: 19 } }), 'Core: Cool 26°C / Heat 18°C; Perimeter_N: Cool 25°C / Heat 19°C');
});
