# Eco-Loop Building Agents — Technical Architecture Audit & Engineering Review

This document provides a factual, in-depth engineering audit of the **Eco_Loop_Building_Agents** repository, evaluating its architecture, physical simulation rigor, asynchronous concurrency model, and production readiness.

---

### 1. Architectural Overview & Problem Formulation

**Core Problem:**  
Commercial HVAC systems account for substantial building electrical energy use. Static thermostat schedules fail to adapt to dynamic occupancy patterns, solar thermal gains, and outdoor ambient temperature variations.

**System Approach:**  
Eco-Loop deploys an autonomous control loop that samples multi-zone thermal telemetry every 30 seconds, queries an AI decision agent with building context, and applies validated HVAC setpoints to maintain occupant thermal comfort (ASHRAE Standard 55) while minimizing energy draw.

```
[Simulation / EnergyPlus] <--> [State Store (RLock)] <--> [FastMCP 3.x ASGI]
           ^                             ^                        ^
           | (Every 30s)                 |                        | (SSE/HTTP)
[Autonomous Controller] --------> [AI Agent (Ollama)]     [External MCP Clients]
           |
           +--------------------> [WebSocket Broadcaster] --> [React Dashboard]
```

---

### 2. Technology Stack & Component Analysis

| Layer | Implementation | Evaluation |
|---|---|---|
| **API & Web Framework** | FastAPI, Starlette, Uvicorn | High performance, lifespan context manager properly coordinates FastMCP TaskGroups. |
| **Concurrency Model** | Python `asyncio` + `threading.RLock` | Async control loop with non-blocking LLM calls; thread-safe state store for concurrent API/MCP readers. |
| **Physics Simulation** | Python Thermal Mass Fallback / EnergyPlus 24.1 API | Multi-zone differential thermal equation; orientation-aware solar radiation; Newton-Raphson ISO 7730 PMV/PPD computation. |
| **Agent / Local LLM** | Ollama with `qwen2.5:7b` (AsyncClient) | Pydantic JSON schema structured output; bounded retry and deterministic rule-based fallback. |
| **Agent Protocol** | FastMCP 3.x (10 registered tools) | Standards-compliant Model Context Protocol server exposing building state and actuators. |
| **Telemetry Streaming** | WebSockets (`/ws`) | Dynamic client origin negotiation; exponential backoff reconnection with heartbeat ping. |
| **Frontend Dashboard** | React 18, Vite, Tailwind CSS, Chart.js | Responsive grid layout; live charting; error boundary resilience. |

---

### 3. Engineering Audit Findings & Remediation

#### A. Baseline Energy Accounting (P0 — Remediated)
* **Pre-remediation Issue:** The dashboard calculated baseline energy by multiplying actual energy consumption by a static synthetic factor (1.15), masking real physical variance.
* **Remediation:** Implemented an independent fixed-setpoint reference simulation (`SimulatedBuildingEnvironment(is_baseline=True)`) running identically seeded weather, building mass, and schedules. Measured energy savings are computed directly from physical kWh values:  
  $$\text{Energy Savings (\%)} = \frac{\text{Baseline kWh} - \text{Controlled kWh}}{\text{Baseline kWh}} \times 100$$

#### B. Asynchronous Event Loop Blocking (P0 — Remediated)
* **Pre-remediation Issue:** `llm_agent.py` invoked synchronous `ollama.Client.chat()` from inside an async coroutine with blocking retry sleep, stalling simulation stepping and WebSocket broadcasting during inference.
* **Remediation:** Refactored to `ollama.AsyncClient` with `asyncio.wait_for()` enforcing configured `LLM_TIMEOUT_SECONDS`, async sleep between retries, and clean task cancellation handling.

#### C. LLM Availability & Recovery (P1 — Remediated)
* **Pre-remediation Issue:** Ollama availability was checked only once during process startup. If Ollama started later or restarted, the system remained locked in fallback mode indefinitely.
* **Remediation:** Implemented throttled background health checks (`check_availability()`) that safely probe Ollama and restore active LLM inference automatically when the service recovers.

#### D. FastMCP Lifespan & Mounting (P0 — Remediated)
* **Pre-remediation Issue:** FastMCP 3.x requires its `lifespan` context manager to run inside the parent FastAPI application to initialize session taskgroups. Without this, external MCP calls failed with runtime taskgroup errors.
* **Remediation:** Integrated `mcp_asgi_app.lifespan` into the FastAPI `lifespan` handler and registered all 10 MCP tools, including `run_simulation_step`.

#### E. ISO 7730 PMV/PPD Thermal Balance (P1 — Remediated)
* **Pre-remediation Issue:** Newton-Raphson iteration in `_pmv_ppd()` solved an objective equation that canceled out thermal load, resulting in near-zero PMV values under extreme temperatures.
* **Remediation:** Corrected the clothing heat balance equation to balance clothing conduction against outer surface radiative and convective losses, producing standard ISO 7730 PMV outputs across hot (+3.0) and cold (-3.0) extremes.

---

### 4. Registered MCP Tool Specifications (10 Tools)

The FastMCP server exposes 10 distinct tools at `/mcp/`:

1. `read_building_state`: Complete building snapshot (temperatures, setpoints, comfort indices, power draw).
2. `get_hvac_setpoints`: Active cooling and heating setpoints and deadband for all zones.
3. `update_setpoint`: Adjust thermostat setpoints for a specified zone with deadband validation.
4. `update_all_setpoints`: Uniformly update setpoints across all 5 zones simultaneously.
5. `run_simulation_step`: Advance the physics simulation environment by one discrete timestep on demand.
6. `get_energy_usage`: Cumulative energy consumption (kWh), instantaneous power (kW), and peak demand.
7. `calculate_savings`: Comparative energy savings, percentage reduction, and avoided CO₂ emissions.
8. `get_comfort_report`: Per-zone PMV/PPD metrics and ASHRAE 55 compliance verification.
9. `get_outdoor_conditions`: Ambient temperature, relative humidity, diurnal phase, and seasonal context.
10. `get_ai_decision`: Most recent AI decision, structured setpoint recommendations, and plain-English reasoning.

---

### 5. Production Readiness & Remaining Limitations

1. **Persistence:** State history is currently maintained in memory with an in-process ring buffer (`collections.deque`). Production enterprise deployment requires a persistent time-series database (e.g., TimescaleDB or InfluxDB).
2. **Control Algorithm:** Zero-shot LLM inference provides interpretable natural language reasoning suitable for supervisory setpoint optimization. Further efficiency gains could be achieved via hybrid Model Predictive Control (MPC) or Reinforcement Learning (PPO) fine-tuned on EnergyPlus traces.
3. **Hardware Runtime:** Running local 7B-parameter models requires a capable GPU (e.g., RTX 3050+ or Apple Silicon) for sub-second responses. The validated rule-based fallback guarantees continuous 100% building uptime on low-power host environments.
