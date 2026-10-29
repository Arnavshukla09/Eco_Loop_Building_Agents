# Eco-Loop System Evaluation Report

> **Generated:** 2026-10-29 04:43:03 UTC  
> **Evaluation Scope:** 1 Full Day (96 timesteps × 15 min) | Seeds: `[42, 101, 2024]` | CO₂ Factor: 0.386 kg/kWh  
> **Active Dynamic Controller Under Test:** `Rule-Based Dynamic Controller (Deterministic Algorithm)`

## 1. Executive Summary & HVAC Performance

This evaluation measures the performance of the Eco-Loop autonomous controller against a true fixed-setpoint reference baseline (cooling 22.0°C, heating 21.0°C). Conditions are matched identically across random seeds.

| Metric                                    | Measured Value                                          |
|-------------------------------------------|---------------------------------------------------------|
| Active Dynamic Controller                 | Rule-Based Dynamic Controller (Deterministic Algorithm) |
| Reference Baseline Energy (Mean)          | 142.39 kWh                                              |
| Eco-Loop Controlled Energy (Mean)         | 77.43 kWh                                               |
| Measured Energy Savings (Mean ± Std)      | 45.62% ± 0.45%                                          |
| Peak Electrical Demand Reduction          | 8.87%                                                   |
| Average CO₂ Avoided (24 h)                | 25.08 kg                                                |
| ASHRAE 55 Comfort Adherence (|PMV| ≤ 0.5) | 63.1%                                                   |
| Average PMV (Comfort Index)               | -0.09                                                   |

### Multi-Seed Breakdown (24-Hour Simulation)

|   Seed | Controller Mode               |   Baseline (kWh) |   Controlled (kWh) | Savings (%)   | Peak Red. (%)   |   Mean PMV | Comfort (%)   |
|--------|-------------------------------|------------------|--------------------|---------------|-----------------|------------|---------------|
|     42 | Rule-Based Dynamic Controller |           141    |              76.57 | +45.7%        | +13.5%          |      -0.09 | 63.1%         |
|    101 | Rule-Based Dynamic Controller |           142.71 |              78.29 | +45.1%        | +11.1%          |      -0.09 | 65.6%         |
|   2024 | Rule-Based Dynamic Controller |           143.46 |              77.43 | +46.0%        | +2.0%           |      -0.06 | 62.9%         |

### Live Ollama LLM Inference Benchmark (5 Timesteps, Seed 42)

| Benchmark Metric                | Observed Value     |
|---------------------------------|--------------------|
| Controller Mode                 | LLM (qwen2.5:1.5b) |
| Successful LLM Calls            | 5/5 (0 Fallbacks)  |
| Mean Inference Latency          | 4.78 s / decision  |
| Comfort Adherence (|PMV| ≤ 0.5) | 12.0%              |

## 2. MCP Tool Performance (10 Registered Tools)

| Tool Name              | Median Latency   | Status   |
|------------------------|------------------|----------|
| read_building_state    | 0.011 ms         | Success  |
| get_hvac_setpoints     | 0.021 ms         | Success  |
| update_setpoint        | 0.039 ms         | Success  |
| update_all_setpoints   | 0.016 ms         | Success  |
| run_simulation_step    | 0.007 ms         | Success  |
| get_energy_usage       | 0.056 ms         | Success  |
| calculate_savings      | 0.041 ms         | Success  |
| get_comfort_report     | 0.041 ms         | Success  |
| get_outdoor_conditions | 0.025 ms         | Success  |
| get_ai_decision        | 0.007 ms         | Success  |

## 3. Fault Tolerance & Resilience

Evaluation of controller behavior under injected physical, communication, and model faults:

| Fault Scenario              | Handler Action                      | System Impact                              |
|-----------------------------|-------------------------------------|--------------------------------------------|
| LLM Disconnect              | 5/5 Fallback Actions                | 100% Graceful Recovery via Rule-Based Path |
| LLM Timeout                 | 5/5 Fallback Actions                | 100% Graceful Recovery via Rule-Based Path |
| Corrupt Model JSON          | 5/5 Fallback Actions                | 100% Graceful Recovery via Rule-Based Path |
| Sensor NaN Dropout          | Fault Flagged + Neighbor Imputation | Passed (Valid Comfort Indices Retained)    |
| Polar Vortex Freeze (-20°C) | Heating Floor Maintained            | Passed (Indoor T ≥ 16°C across all zones)  |
| System Crash Count          | 0 Crashes                           | Healthy Uptime Maintained                  |

## 4. Deployment & System Health

| Parameter             | Status                    |
|-----------------------|---------------------------|
| CPU Utilization       | 6.8%                      |
| Process Memory (RAM)  | 166.1 MB                  |
| Ollama Host Reachable | Yes                       |
| Configured LLM Model  | qwen2.5:1.5b              |
| Simulation Mode       | Python Thermal Mass Model |

## 5. Methodology & Empirical Limitations

- **Methodology**: Evaluated against a reference fixed setpoint baseline using identical building parameters, weather inputs, and initial conditions.
- **Physics Model**: Runs the validated Python thermal-mass fallback engine with Newton-Raphson ISO 7730 Fanger PMV/PPD modeling.
- **Extrapolation Notice**: 24-hour evaluation results represent measured single-day simulation dynamics. Long-term annual projections must account for seasonal variations across summer and winter weather conditions.

## Visualization

![Energy Comparison](energy_comparison.png)
