# Honeywell Eco-Loop Building Agents

> Autonomous Physical AI for Smart Building HVAC Energy Optimization and Thermal Comfort Control

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green.svg)](https://fastapi.tiangolo.com/)
[![EnergyPlus](https://img.shields.io/badge/EnergyPlus-24.1-orange.svg)](https://energyplus.net/)
[![LLM](https://img.shields.io/badge/LLM-Qwen2.5--1.5B%20%7C%207B-purple.svg)](https://ollama.com/)
[![MCP](https://img.shields.io/badge/MCP-FastMCP-red.svg)](https://gofastmcp.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## What It Does

Eco-Loop is an autonomous AI system that controls building HVAC setpoints in real time using a local open-source LLM. It:

1. **Simulates** a 5-zone office building with realistic thermal physics (or connects to real EnergyPlus)
2. **Exposes** building sensors and actuators as 10 Model Context Protocol (MCP) tools
3. **Uses Qwen2.5** (configurable, e.g. 1.5B or 7B via Ollama) to analyze building conditions and issue HVAC decisions as structured JSON
4. **Applies** setpoint changes autonomously with safe deadbands (minimum 1.5°C gap)
5. **Falls back** transparently to a deterministic rule-based controller if the LLM inference server is offline
6. **Streams** live telemetry to a reactive React dashboard via WebSockets

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│              React Dashboard (port 5173/8000)           │
│        Temperature │ Energy │ Comfort │ AI Decision     │
└──────────────────────┬──────────────────────────────────┘
                       │ WebSocket (/ws)
┌──────────────────────▼──────────────────────────────────┐
│                 FastAPI Backend (port 8000)              │
│   REST API  │  WebSocket Broadcast  │  MCP SSE (/mcp)   │
└──────┬────────────────────────────────────┬─────────────┘
       │                                    │
┌──────▼──────────┐                ┌────────▼────────────┐
│   MCP Server    │                │   Shared State      │
│   (FastMCP)     │◄──────────────►│   (BuildingState)   │
│  10 AI Tools    │                └────────┬────────────┘
└─────────────────┘                         │
                                   ┌────────▼────────────┐
                                   │    AI Agent Loop     │
                                   │  Ollama + Qwen2.5   │
                                   │  Every 30 seconds   │
                                   └────────┬────────────┘
                                            │ setpoints
                                   ┌────────▼────────────┐
                                   │ EnergyPlus / Sim    │
                                   │  5-zone building    │
                                   │  Physics model      │
                                   └─────────────────────┘
```

---

## Project Structure

```
eco-loop/
├── run.py                     # 🚀 Single-command launcher
├── requirements.txt
├── docker-compose.yml
├── Dockerfile
├── .env.example               # Copy to .env and customise
│
├── config/
│   └── settings.py            # All settings (env vars)
│
├── backend/
│   ├── app.py                 # FastAPI application + lifespan
│   ├── models.py              # Pydantic data models
│   ├── state.py               # Thread-safe shared state store
│   ├── energyplus_runner.py   # EnergyPlus wrapper + physics sim
│   ├── llm_agent.py           # Ollama/Qwen2.5 AI agent
│   ├── mcp_server.py          # FastMCP server (10 tools)
│   ├── controller.py          # Autonomous control loop
│   └── dashboard_api.py       # WebSocket connection manager
│
├── energyplus/
│   └── building.idf           # 5-zone office building model
│
├── frontend/                  # React + Vite + TailwindCSS
│   ├── src/
│   │   ├── App.jsx
│   │   ├── hooks/useWebSocket.js
│   │   └── components/
│   │       ├── MetricCard.jsx
│   │       ├── AIDecisionPanel.jsx
│   │       ├── TemperatureChart.jsx
│   │       ├── EnergyChart.jsx
│   │       ├── ComfortGauge.jsx
│   │       ├── ZoneGrid.jsx
│   │       └── SavingsCounter.jsx
│   └── package.json
│
├── docs/
│   └── demo_script.md
└── presentation/
    └── slides.md
```

---

## Quick Start

### Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10+ | Required |
| Node.js | 18+ | For frontend |
| Ollama | Latest | For local LLM |
| EnergyPlus | 24.1 | Optional (sim mode works without it) |

### Step 1: Clone and Install

```bash
git clone <repo-url>
cd eco-loop

# Install Python dependencies
pip install -r requirements.txt

# Copy environment config
cp .env.example .env
```

### Step 2: Set up Ollama (for AI decisions)

```bash
# Install Ollama from https://ollama.com
# Then pull the model:
ollama pull qwen2.5:7b

# Start the Ollama server (keep this running)
ollama serve
```

> **Note**: If Ollama is unavailable, the system automatically uses a rule-based controller. It still works — just without LLM reasoning.

### Step 3: Launch

```bash
python run.py
```

This will:
- Check all dependencies
- Build the React frontend
- Start the FastAPI server at `http://localhost:8000`

**Dashboard:** http://localhost:8000  
**API docs:** http://localhost:8000/docs  
**MCP tools:** http://localhost:8000/mcp/

### Frontend Development Mode

```bash
cd frontend
npm install
npm run dev    # Runs on http://localhost:5173
```

### Docker (Full Stack)

```bash
docker-compose up --build
```

---

## Configuration

Edit `.env` to customise:

| Variable | Default | Description |
|---|---|---|
| `SIMULATION_MODE` | `true` | `true` = physics sim, `false` = real EnergyPlus |
| `ENERGYPLUS_PATH` | `C:/EnergyPlus-24-1-0` | EnergyPlus install path |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL |
| `LLM_MODEL` | `qwen2.5:7b` | Model to use (also supports `llama3:8b`) |
| `AGENT_INTERVAL_SECONDS` | `30` | How often AI makes a decision |
| `SPEEDUP_FACTOR` | `60` | Sim speedup (60x: 15s wall-clock per 15-min simulated step) |
| `API_PORT` | `8000` | Dashboard port |

---

## MCP Tools

The MCP server exposes **10 tools** accessible at `/mcp/`:

| Tool | Description |
|---|---|
| `read_building_state` | Full zone temps, setpoints, comfort, energy |
| `get_hvac_setpoints` | Current setpoints per zone |
| `update_setpoint` | Change one zone's setpoints |
| `update_all_setpoints` | Change all zones at once |
| `run_simulation_step` | Advance physics simulation one timestep |
| `get_energy_usage` | Cumulative kWh + peak demand |
| `calculate_savings` | Savings vs baseline (kWh, %, CO₂) |
| `get_comfort_report` | PMV/PPD per zone + ASHRAE 55 compliance |
| `get_outdoor_conditions` | Weather, season, time of day |
| `get_ai_decision` | Last LLM decision + reasoning |

These can be called from any MCP-compatible client (Claude Desktop, Cursor, etc.).

---

## REST API

| Endpoint | Method | Description |
|---|---|---|
| `/api/status` | GET | Full current state |
| `/api/history?limit=N` | GET | Historical data points |
| `/api/health` | GET | System health check |
| `/api/setpoint` | POST | Manual setpoint override |
| `/api/mcp/tools` | GET | List available MCP tools |
| `/ws` | WS | Real-time WebSocket stream |

---

## Dashboard Panels

| Panel | Metrics |
|---|---|
| **Metric Cards** | Avg Temperature, HVAC Power, Comfort Score, Energy Savings %, CO₂ Saved |
| **AI Decision** | Current mode, reasoning, confidence, setpoints per zone |
| **Temperature Chart** | 5-zone temperature history + setpoint bands |
| **Energy Chart** | Actual vs baseline power, savings area |
| **Comfort Gauge** | PMV gauge, PPD score, ASHRAE 55 compliance |
| **Zone Grid** | All zones: temp, setpoints, PMV, humidity, status |

---

## AI Agent Logic & Controller Modes

The autonomous controller operates in two complementary modes:

1. **LLM Mode (Qwen2.5 via Ollama):**
   - Reads zone telemetry, occupancy, outdoor weather, and historical trends.
   - Formats a structured context prompt with live building snapshots.
   - Generates structured JSON adhering to the `AgentDecision` Pydantic schema.
   - Evaluates reasoning, confidence scores, and dynamic setpoints with safety deadband enforcement.
2. **Rule-Based Dynamic Controller (Offline Fallback):**
   - Automatically activates if Ollama is unreachable, times out (>30s), or returns corrupt output.
   - Performs ASHRAE 55 comfort-compliant setback calculations and scheduled occupancy deadband expansion.
   - Guarantees 100% building system availability without external LLM dependencies.

### Sample AI Decision JSON
```json
{
  "zone_setpoints": {
    "Core":        {"cooling": 25.0, "heating": 19.0},
    "Perimeter_N": {"cooling": 24.0, "heating": 20.0},
    "Perimeter_S": {"cooling": 25.5, "heating": 19.5},
    "Perimeter_E": {"cooling": 24.5, "heating": 19.5},
    "Perimeter_W": {"cooling": 24.5, "heating": 19.5}
  },
  "fan_speed": "medium",
  "energy_mode": "eco",
  "reasoning": "Occupancy at 60% with outdoor temp of 8°C. Widening deadband on south-facing perimeter zones to reduce cooling load while maintaining ASHRAE 55 comfort targets. Estimated 14% savings versus baseline.",
  "confidence": 0.88,
  "estimated_savings_pct": 14.2
}
```

---

## Security & Access Control

Mutating REST endpoints (`POST /api/setpoint`, `POST /api/simulation/speed`) can be protected using an optional bearer token:

- Configure `API_KEY=your-secret-token` in `.env`.
- Mutating requests must supply `Authorization: Bearer <your-secret-token>`.
- Read-only endpoints (`/api/status`, `/api/health`, `/api/history`, WebSocket stream `/ws`) remain open for live dashboard monitoring.

---

## Simulation Physics & Baseline Methodology

When `SIMULATION_MODE=true`, a validated thermal physics engine simulates the building:

- **Thermal mass model**: `ΔT = ΣQ · Δt / (ρ · Cₚ · V)`
- **Heat sources**: Solar radiation (orientation-specific solar gains), occupant metabolic loads, lighting, and internal equipment
- **Heat loss**: Multi-layer building envelope conductance
- **HVAC model**: Proportional heating/cooling controller, COP 3.5 cooling / 1.0 heating
- **Thermal Comfort**: Newton-Raphson solved Fanger PMV/PPD model (ISO 7730 standard)
- **Reference Baseline**: Side-by-side parallel simulation with fixed reference setpoints (22.0°C cooling / 21.0°C heating) receiving matched weather and occupancy sequences.

---

## Key System Capabilities

| Capability | Implementation |
|---|---|
| ✅ Python Backend | FastAPI async lifespan + non-blocking worker |
| ✅ HVAC Simulation | Parallel reference baseline + physics simulator |
| ✅ LLM & Fallback | Qwen2.5 async inference + rule-based fallback |
| ✅ MCP Server | FastMCP with 10 registered tools at `/mcp/` |
| ✅ Live Dashboard | React 18 + Vite + TailwindCSS + Chart.js |
| ✅ Safe Closed-Loop | Step lock preventing concurrent simulation races |
| ✅ Security Guard | Optional Bearer API key protection on mutating routes |
| ✅ Automated Testing | Pytest test suite covering simulation, state, and APIs |
| ✅ Empirical Evaluation | Multi-seed 24h benchmark in `evaluation_report.md` |

---

## Future Scope

- **Reinforcement learning**: Hybrid RL + LLM policy trained on multi-year simulation runs
- **Model Predictive Control (MPC)**: Multi-step horizon optimization using weather forecasts
- **BACnet / Modbus Connectors**: Real hardware building management system integration adapters
- **Multi-building fleet orchestration**: Campus-wide demand response and load shifting

---

## License

MIT License — See [LICENSE](LICENSE) file.
