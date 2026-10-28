# Eco-Loop System Evaluation Report

> **Generated:** 2026-10-28 14:05:44 UTC  
> **Evaluation Scope:** 1 Full Day (96 timesteps × 15 min) | Seeds: `[42, 101, 2024]` | CO₂ Factor: 0.386 kg/kWh

## 1. Executive Summary & HVAC Performance

This evaluation measures the performance of the Eco-Loop autonomous controller against a true fixed-setpoint reference baseline (cooling 22.0°C, heating 21.0°C). Conditions are matched identically across random seeds.

| Metric                                    | Measured Value   |
|-------------------------------------------|------------------|
| Reference Baseline Energy (Mean)          | 142.39 kWh       |
| Eco-Loop Controlled Energy (Mean)         | 77.43 kWh        |
| Measured Energy Savings (Mean ± Std)      | 45.62% ± 0.45%   |
| Peak Electrical Demand Reduction          | 8.87%            |
| Average CO₂ Avoided (24 h)                | 25.08 kg         |
| ASHRAE 55 Comfort Adherence (|PMV| ≤ 0.5) | 63.1%            |
| Average PMV (Comfort Index)               | -0.09            |

### Multi-Seed Breakdown (24-Hour Simulation)

|   Seed |   Baseline (kWh) |   Controlled (kWh) | Savings (%)   | Peak Red. (%)   |   Mean PMV | Comfort (%)   |
|--------|------------------|--------------------|---------------|-----------------|------------|---------------|
|     42 |           141    |              76.57 | +45.7%        | +13.5%          |      -0.09 | 63.1%         |
|    101 |           142.71 |              78.29 | +45.1%        | +11.1%          |      -0.09 | 65.6%         |
|   2024 |           143.46 |              77.43 | +46.0%        | +2.0%           |      -0.06 | 62.9%         |

## 2. MCP Tool Performance (10 Registered Tools)

| Tool Name              | Median Latency   | Status   |
|------------------------|------------------|----------|
| read_building_state    | 0.011 ms         | Success  |
| get_hvac_setpoints     | 0.023 ms         | Success  |
| update_setpoint        | 0.006 ms         | Success  |
| update_all_setpoints   | 0.003 ms         | Success  |
| run_simulation_step    | 0.002 ms         | Success  |
| get_energy_usage       | 0.021 ms         | Success  |
| calculate_savings      | 0.018 ms         | Success  |
| get_comfort_report     | 0.015 ms         | Success  |
| get_outdoor_conditions | 0.010 ms         | Success  |
| get_ai_decision        | 0.002 ms         | Success  |

## 3. Fault Tolerance & Resilience

Evaluation of controller behavior under injected communication and data faults (10 cycles each):

| Fault Scenario     | Handler Action        | System Impact             |
|--------------------|-----------------------|---------------------------|
| LLM Disconnect     | 0/10 Fallback Actions | 100% Graceful Recovery    |
| LLM Timeout        | 0/10 Fallback Actions | 100% Graceful Recovery    |
| Corrupt Model JSON | 0/10 Fallback Actions | 100% Graceful Recovery    |
| System Crash Count | 0 Crashes             | Healthy Uptime Maintained |

## 4. Deployment & System Health

| Parameter             | Status                    |
|-----------------------|---------------------------|
| CPU Utilization       | 11.9%                     |
| Process Memory (RAM)  | 137.8 MB                  |
| Ollama Host Reachable | No (Offline Evaluation)   |
| Configured LLM Model  | qwen2.5:7b                |
| Simulation Mode       | Python Thermal Mass Model |

## 5. Methodology & Empirical Limitations

- **Methodology**: Evaluated against a reference fixed setpoint baseline using identical building parameters, weather inputs, and initial conditions.
- **Physics Model**: Runs the validated Python thermal-mass fallback engine with Newton-Raphson ISO 7730 Fanger PMV/PPD modeling.
- **Extrapolation Notice**: 24-hour evaluation results represent measured single-day simulation dynamics. Long-term annual projections must account for seasonal variations across summer and winter weather conditions.

## Visualization

![Energy Comparison](energy_comparison.png)
