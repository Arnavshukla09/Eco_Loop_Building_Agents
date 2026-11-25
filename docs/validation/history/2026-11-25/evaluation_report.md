# Eco-Loop System Evaluation Report

> **Generated:** 2026-11-25 17:44:36 UTC
> **Evaluation Scope:** 1 Full Day (96 timesteps Ã— 15 min) | Seeds: `[42, 101, 2024]` | COâ‚‚ Factor: 0.386 kg/kWh
> **Active Dynamic Controller Under Test:** `Rule-Based Dynamic Controller (Deterministic Algorithm)`

## 1. Executive Summary & Balanced Baseline Comparison

This evaluation measures the performance of the Eco-Loop autonomous controller against a true fixed-setpoint reference baseline (cooling 22.0Â°C, heating 21.0Â°C). All initial conditions, thermal envelope parameters, and weather time-series are identically matched across seeds.

| Metric                          | Reference Baseline (Fixed 22/21Â°C)   | Eco-Loop Controlled   | Delta / Impact            |
|---------------------------------|--------------------------------------|-----------------------|---------------------------|
| Total Energy (Mean Â± Std)       | 142.39 Â± 1.26 kWh                    | 77.43 Â± 0.86 kWh      | -45.62% Â± 0.45% energy    |
| Peak Electrical Demand          | 20.90 kW                             | 19.05 kW              | -8.87% demand reduction   |
| Avoided COâ‚‚ Emissions (24 h)    | Reference (0.00 kg)                  | 25.08 kg              | +25.08 kg avoided         |
| ASHRAE 55 Comfort (|PMV| â‰¤ 0.5) | 52.2% Â± 0.7%                         | 63.9% Â± 1.5%          | +11.7 percentage points   |
| Mean PMV (Comfort Index)        | -0.572                               | -0.083                | -0.489 drift from neutral |
| Predicted Dissatisfied (PPD)    | 13.2%                                | 10.9%                 | -2.3 points               |

### Multi-Seed Breakdown (24-Hour Simulation Across Seeds)

|   Seed | Controller Mode               |   Base (kWh) |   Ctrl (kWh) | Savings (%)   |   COâ‚‚ Avoided (kg) | Peak Red. (%)   | Base Comfort   | Ctrl Comfort   |   Ctrl PMV |
|--------|-------------------------------|--------------|--------------|---------------|--------------------|-----------------|----------------|----------------|------------|
|     42 | Rule-Based Dynamic Controller |       141    |        76.57 | +45.7%        |              24.87 | +13.5%          | 51.7%          | 63.1%          |      -0.09 |
|    101 | Rule-Based Dynamic Controller |       142.71 |        78.29 | +45.1%        |              24.87 | +11.1%          | 52.9%          | 65.6%          |      -0.09 |
|   2024 | Rule-Based Dynamic Controller |       143.46 |        77.43 | +46.0%        |              25.49 | +2.0%           | 51.9%          | 62.9%          |      -0.06 |

## 2. Matched Head-to-Head Comparison (Identical 5 Timesteps, Seed 42)

The available control approaches use identical seeded initial conditions for five timesteps starting at 08:00. Live LLM results are omitted when its configured model is unavailable.

| Metric                          | Fixed Baseline   | Rule-Based Dynamic   | Live LLM (qwen2.5:1.5b)   |
|---------------------------------|------------------|----------------------|---------------------------|
| Total Energy Consumed           | 0.00 kWh         | 0.00 kWh             | N/A                       |
| Energy Savings vs Baseline      | Reference (0.0%) | +0.0%                | N/A                       |
| ASHRAE 55 Comfort (|PMV| â‰¤ 0.5) | 12.0%            | 12.0%                | N/A                       |
| Mean PMV (Comfort Index)        | -0.678           | -0.678               | N/A                       |
| Mean PPD (% Dissatisfied)       | 15.0%            | 15.0%                | N/A                       |
| Controller Fallback Count       | N/A              | 0 (Algorithmic)      | N/A                       |
| Average Decision Latency        | 0.00 ms          | 0.08 ms              | N/A                       |
| Actuator Setpoint Modifications | 0 (Static)       | 0 updates            | N/A                       |

> [!NOTE]
> **Scope**: This short comparison starts at 08:00 and covers five timesteps. It cannot establish day-long LLM energy or comfort performance.

## 3. In-Process MCP Tool Function Latency (N=50 Repetitions)

> [!NOTE]
> **Transport Overhead Distinction**: These benchmarks measure the in-memory Python execution speed of the underlying tool logic. Real MCP clients communicating over stdio or SSE JSON-RPC transport will experience an additional ~1â€“5 ms serialization and IPC/HTTP round-trip overhead.

| Tool Name              |   N | Median   | Mean     | P95      | Min      | Max      | Status   |
|------------------------|-----|----------|----------|----------|----------|----------|----------|
| read_building_state    |  50 | 0.010 ms | 0.011 ms | 0.018 ms | 0.009 ms | 0.038 ms | Success  |
| get_hvac_setpoints     |  50 | 0.022 ms | 0.022 ms | 0.024 ms | 0.020 ms | 0.048 ms | Success  |
| update_setpoint        |  50 | 0.059 ms | 0.064 ms | 0.085 ms | 0.052 ms | 0.194 ms | Success  |
| update_all_setpoints   |  50 | 0.222 ms | 0.234 ms | 0.348 ms | 0.195 ms | 0.392 ms | Success  |
| run_simulation_step    |  50 | 0.533 ms | 0.566 ms | 0.682 ms | 0.469 ms | 1.339 ms | Success  |
| get_energy_usage       |  50 | 0.020 ms | 0.021 ms | 0.029 ms | 0.020 ms | 0.042 ms | Success  |
| calculate_savings      |  50 | 0.018 ms | 0.018 ms | 0.021 ms | 0.017 ms | 0.028 ms | Success  |
| get_comfort_report     |  50 | 0.015 ms | 0.017 ms | 0.023 ms | 0.015 ms | 0.036 ms | Success  |
| get_outdoor_conditions |  50 | 0.009 ms | 0.010 ms | 0.011 ms | 0.009 ms | 0.033 ms | Success  |
| get_ai_decision        |  50 | 0.005 ms | 0.005 ms | 0.006 ms | 0.004 ms | 0.019 ms | Success  |

## 4. Fault Tolerance & Actuation Resilience

Evaluation of controller behavior under injected physical, network, and model failure modes:

| Fault Scenario                      | Handler Action                      | Verification Result                                              |
|-------------------------------------|-------------------------------------|------------------------------------------------------------------|
| LLM Network Disconnect              | 5/5 Fallback Actions                | 100% Graceful Fallback (Real port connection refusal)            |
| LLM Request Timeout                 | 5/5 Fallback Actions                | Fallback after forced HTTP failure (timeout or connection error) |
| Malformed Model Response            | 5/5 Fallback Actions                | 100% Caught by BuildingAIAgent and routed to fallback            |
| Fallback Actuator Actuation         | All 5 Zones Updated on Environment  | Passed (Actuators received and applied fallback setpoints)       |
| Sensor Dropout (NaN / Disconnect)   | Anomalous reading flagged & imputed | Passed (Comfort scores calculable without numerical error)       |
| Polar Vortex Freeze (-20Â°C ambient) | Heating Floor Maintained            | Passed (Indoor T â‰¥ 16.0Â°C across all zones)                      |
| System Crash / Panic Count          | 0 Crashes                           | Healthy Uptime Maintained                                        |

## 5. Deployment Health & Resource Usage

| System Component         | Observed State                     |
|--------------------------|------------------------------------|
| Host CPU Utilization     | 27.4%                              |
| Process Memory (RSS RAM) | 161.7 MB                           |
| Local Ollama Server      | Offline                            |
| Verified LLM Model       | Unavailable (not verified)         |
| Simulation Engine        | Python ISO 7730 Thermal Mass Model |

## 6. Methodology & Empirical Limitations

- **Matched Evaluation**: Reference fixed baseline and controlled environments share identical building dimensions, thermal mass coefficients ($1.8\times 10^7$ to $4.5\times 10^7$ J/K), weather profiles, and occupant density.
- **Emission Modeling**: COâ‚‚ calculations use an un-clamped factor of 0.386 kg/kWh, preserving negative emissions penalties whenever a controller consumes more energy than the baseline.
- **Comfort Standard**: Thermal comfort evaluates ASHRAE Standard 55 / ISO 7730 Predicted Mean Vote (PMV) neutral target ($-0.5 \le \text{PMV} \le +0.5$) with 15-minute sampling across all zones.
- **Extrapolation Bounds**: 24-hour evaluation results capture diurnal day-night heating and cooling cycles. Full annual building performance requires multi-season simulation runs across summer and winter weather files.

## Visualization

![Energy Comparison](energy_comparison.png)
