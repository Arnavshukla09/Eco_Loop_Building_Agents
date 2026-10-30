# Eco-Loop System Evaluation Report

> **Generated:** 2026-10-29 07:23:35 UTC  
> **Evaluation Scope:** 1 Full Day (96 timesteps × 15 min) | Seeds: `[42, 101, 2024]` | CO₂ Factor: 0.386 kg/kWh  
> **Active Dynamic Controller Under Test:** `Rule-Based Dynamic Controller (Deterministic Algorithm)`

## 1. Executive Summary & Balanced Baseline Comparison

This evaluation measures the performance of the Eco-Loop autonomous controller against a true fixed-setpoint reference baseline (cooling 22.0°C, heating 21.0°C). All initial conditions, thermal envelope parameters, and weather time-series are identically matched across seeds.

| Metric                          | Reference Baseline (Fixed 22/21°C)   | Eco-Loop Controlled   | Delta / Impact            |
|---------------------------------|--------------------------------------|-----------------------|---------------------------|
| Total Energy (Mean ± Std)       | 142.39 ± 1.26 kWh                    | 77.43 ± 0.86 kWh      | -45.62% ± 0.45% energy    |
| Peak Electrical Demand          | 20.90 kW                             | 19.05 kW              | -8.87% demand reduction   |
| Avoided CO₂ Emissions (24 h)    | Reference (0.00 kg)                  | 25.08 kg              | +25.08 kg avoided         |
| ASHRAE 55 Comfort (|PMV| ≤ 0.5) | 52.2% ± 0.7%                         | 63.9% ± 1.5%          | +11.7 percentage points   |
| Mean PMV (Comfort Index)        | -0.572                               | -0.083                | -0.489 drift from neutral |
| Predicted Dissatisfied (PPD)    | 13.2%                                | 10.9%                 | -2.3 points               |

### Multi-Seed Breakdown (24-Hour Simulation Across Seeds)

|   Seed | Controller Mode               |   Base (kWh) |   Ctrl (kWh) | Savings (%)   |   CO₂ Avoided (kg) | Peak Red. (%)   | Base Comfort   | Ctrl Comfort   |   Ctrl PMV |
|--------|-------------------------------|--------------|--------------|---------------|--------------------|-----------------|----------------|----------------|------------|
|     42 | Rule-Based Dynamic Controller |       141    |        76.57 | +45.7%        |              24.87 | +13.5%          | 51.7%          | 63.1%          |      -0.09 |
|    101 | Rule-Based Dynamic Controller |       142.71 |        78.29 | +45.1%        |              24.87 | +11.1%          | 52.9%          | 65.6%          |      -0.09 |
|   2024 | Rule-Based Dynamic Controller |       143.46 |        77.43 | +46.0%        |              25.49 | +2.0%           | 51.9%          | 62.9%          |      -0.06 |

## 2. Matched Head-to-Head Comparison (Identical 5 Timesteps, Seed 42)

To ensure a rigorous, matched evaluation without transient duration distortion, all three control approaches were executed from the identical initial state, weather sequence, and occupancy schedule (00:00 to 01:15 simulation time):

| Metric                          | Fixed Baseline   | Rule-Based Dynamic   | Live LLM (qwen2.5:1.5b)   |
|---------------------------------|------------------|----------------------|---------------------------|
| Total Energy Consumed           | 0.00 kWh         | 0.00 kWh             | 0.00 kWh                  |
| Energy Savings vs Baseline      | Reference (0.0%) | +0.0%                | +0.0%                     |
| ASHRAE 55 Comfort (|PMV| ≤ 0.5) | 12.0%            | 12.0%                | 12.0%                     |
| Mean PMV (Comfort Index)        | -0.678           | -0.678               | -0.678                    |
| Mean PPD (% Dissatisfied)       | 15.0%            | 15.0%                | 15.0%                     |
| Controller Fallback Count       | N/A              | 0 (Algorithmic)      | 0/5                       |
| Average Decision Latency        | 0.00 ms          | 0.03 ms              | 4.53 s                    |
| Actuator Setpoint Modifications | 0 (Static)       | 0 updates            | 0 updates                 |

> [!NOTE]
> **Thermal Transient Explanation**: In the initial 5 timesteps (cold building startup at midnight), all three controllers (Baseline, Rule-Based, and Live LLM) show an identical **12.0%** comfort adherence because the envelope starts slightly cool (-0.68 PMV) before thermal equilibrium is reached. As the 96-step simulation advances through morning and occupied hours, comfort rises to **63.9%**.

## 3. In-Process MCP Tool Function Latency (N=50 Repetitions)

> [!NOTE]
> **Transport Overhead Distinction**: These benchmarks measure the in-memory Python execution speed of the underlying tool logic. Real MCP clients communicating over stdio or SSE JSON-RPC transport will experience an additional ~1–5 ms serialization and IPC/HTTP round-trip overhead.

| Tool Name              |   N | Median   | Mean     | P95      | Min      | Max        | Status   |
|------------------------|-----|----------|----------|----------|----------|------------|----------|
| read_building_state    |  50 | 0.004 ms | 0.005 ms | 0.006 ms | 0.004 ms | 0.028 ms   | Success  |
| get_hvac_setpoints     |  50 | 0.010 ms | 0.015 ms | 0.029 ms | 0.009 ms | 0.031 ms   | Success  |
| update_setpoint        |  50 | 0.004 ms | 4.776 ms | 0.020 ms | 0.004 ms | 238.533 ms | Success  |
| update_all_setpoints   |  50 | 0.003 ms | 0.003 ms | 0.004 ms | 0.003 ms | 0.007 ms   | Success  |
| run_simulation_step    |  50 | 0.001 ms | 0.001 ms | 0.001 ms | 0.001 ms | 0.003 ms   | Success  |
| get_energy_usage       |  50 | 0.008 ms | 0.012 ms | 0.019 ms | 0.007 ms | 0.185 ms   | Success  |
| calculate_savings      |  50 | 0.007 ms | 0.007 ms | 0.011 ms | 0.006 ms | 0.013 ms   | Success  |
| get_comfort_report     |  50 | 0.007 ms | 0.008 ms | 0.010 ms | 0.006 ms | 0.027 ms   | Success  |
| get_outdoor_conditions |  50 | 0.003 ms | 0.004 ms | 0.005 ms | 0.003 ms | 0.023 ms   | Success  |
| get_ai_decision        |  50 | 0.001 ms | 0.001 ms | 0.001 ms | 0.001 ms | 0.004 ms   | Success  |

## 4. Fault Tolerance & Actuation Resilience

Evaluation of controller behavior under injected physical, network, and model failure modes:

| Fault Scenario                      | Handler Action                      | Verification Result                                           |
|-------------------------------------|-------------------------------------|---------------------------------------------------------------|
| LLM Network Disconnect              | 5/5 Fallback Actions                | 100% Graceful Fallback (Real port connection refusal)         |
| LLM Request Timeout                 | 5/5 Fallback Actions                | 100% Graceful Fallback (Real HTTP timeout aborted in 0.01 ms) |
| Malformed Model Response            | 5/5 Fallback Actions                | 100% Caught by BuildingAIAgent and routed to fallback         |
| Fallback Actuator Actuation         | All 5 Zones Updated on Environment  | Passed (Actuators received and applied fallback setpoints)    |
| Sensor Dropout (NaN / Disconnect)   | Anomalous reading flagged & imputed | Passed (Comfort scores calculable without numerical error)    |
| Polar Vortex Freeze (-20°C ambient) | Heating Floor Maintained            | Passed (Indoor T ≥ 16.0°C across all zones)                   |
| System Crash / Panic Count          | 0 Crashes                           | Healthy Uptime Maintained                                     |

## 5. Deployment Health & Resource Usage

| System Component         | Observed State                     |
|--------------------------|------------------------------------|
| Host CPU Utilization     | 16.1%                              |
| Process Memory (RSS RAM) | 170.9 MB                           |
| Local Ollama Server      | Connected                          |
| Verified LLM Model       | qwen2.5:1.5b                       |
| Simulation Engine        | Python ISO 7730 Thermal Mass Model |

## 6. Methodology & Empirical Limitations

- **Matched Evaluation**: Reference fixed baseline and controlled environments share identical building dimensions, thermal mass coefficients ($1.8\times 10^7$ to $4.5\times 10^7$ J/K), weather profiles, and occupant density.
- **Emission Modeling**: CO₂ calculations use an un-clamped factor of 0.386 kg/kWh, preserving negative emissions penalties whenever a controller consumes more energy than the baseline.
- **Comfort Standard**: Thermal comfort evaluates ASHRAE Standard 55 / ISO 7730 Predicted Mean Vote (PMV) neutral target ($-0.5 \le \text{PMV} \le +0.5$) with 15-minute sampling across all zones.
- **Extrapolation Bounds**: 24-hour evaluation results capture diurnal day-night heating and cooling cycles. Full annual building performance requires multi-season simulation runs across summer and winter weather files.

## Visualization

![Energy Comparison](energy_comparison.png)
