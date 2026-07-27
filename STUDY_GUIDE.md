# Eco-Loop — Complete Project Context & Study Guide

> Everything you need to understand, explain, and extend the Eco-Loop project.
> Study this top-to-bottom before your hackathon presentation or interview.

---

## 1. PROJECT OVERVIEW IN ONE PARAGRAPH

Eco-Loop is an **autonomous Physical AI system** that controls HVAC setpoints in a
5-zone simulated office building. Every 30 seconds it reads building sensor data
through an MCP server, sends that data to a local open-source LLM (Qwen2.5-7B via
Ollama), receives a structured JSON decision, validates it, and applies the new
setpoints to the simulation. A React dashboard shows live charts and the AI's
reasoning. The entire stack runs locally — no cloud, no data sharing.

---

## 2. COMPLETE TECHNOLOGY MAP

```
┌─────────────────────────────────────────────────────────────────────┐
│  LAYER          │  TECHNOLOGY          │  FILE(S)                   │
├─────────────────┼──────────────────────┼────────────────────────────┤
│  Config         │  Pydantic Settings   │  config/settings.py        │
│  Data Models    │  Pydantic v2         │  backend/models.py         │
│  State Store    │  Python threading    │  backend/state.py          │
│  Simulation     │  Custom Physics Eng  │  backend/energyplus_runner │
│  AI Agent       │  Ollama + Qwen2.5    │  backend/llm_agent.py      │
│  MCP Server     │  FastMCP 3.x         │  backend/mcp_server.py     │
│  Control Loop   │  asyncio             │  backend/controller.py     │
│  API            │  FastAPI             │  backend/app.py            │
│  WebSocket      │  Starlette WS        │  backend/dashboard_api.py  │
│  Frontend       │  React 18 + Vite     │  frontend/src/             │
│  Styling        │  TailwindCSS         │  frontend/tailwind.config  │
│  Charts         │  Chart.js            │  frontend/src/components/  │
│  Deployment     │  Docker Compose      │  docker-compose.yml        │
└─────────────────┴──────────────────────┴────────────────────────────┘
```

---

## 3. TOPICS TO STUDY (WITH DEPTH GUIDE)

### A. PYTHON — async / await / asyncio ⭐ CRITICAL

Used everywhere — simulation loop, agent loop, broadcast loop, WebSocket handler.

**What it is:** Python's concurrency model for I/O-bound tasks without threads.

**Key concepts to know:**
- `async def` — defines a coroutine function
- `await` — suspends current coroutine, yields control to event loop
- `asyncio.create_task()` — schedules a coroutine to run concurrently
- `asyncio.sleep(n)` — non-blocking sleep (unlike `time.sleep`)
- Event loop — the engine that runs all coroutines

**Where used in project:**
```python
# backend/controller.py
async def _simulation_loop(self) -> None:
    while self._running:
        obs = await self.env.step()         # await = "pause here, let others run"
        state_store.update_observation(obs)
        await asyncio.sleep(step_wall_time) # non-blocking wait
```

**Study resource:** https://docs.python.org/3/library/asyncio.html

---

### B. PYTHON — Threading & Thread Safety ⭐ IMPORTANT

Used in `state.py` — simulation runs in async context, MCP tools read state from
sync context, so a lock is needed to prevent race conditions.

**Key concepts:**
- `threading.RLock()` — reentrant lock, prevents race conditions
- `with self._lock:` — acquire lock for the block, release after
- **Race condition** — two threads read/write same variable simultaneously → data corruption

**Where used:**
```python
# backend/state.py
class BuildingStateStore:
    def __init__(self):
        self._lock = threading.RLock()   # reentrant lock

    def update_observation(self, obs):
        with self._lock:                  # only one thread at a time
            self._observation = obs
```

---

### C. PYDANTIC v2 ⭐ USED EVERYWHERE

**What it is:** Python library for data validation using type annotations.
Every piece of data in Eco-Loop is a Pydantic model.

```python
from pydantic import BaseModel, Field
from typing import Literal, Dict

class ZoneSetpoint(BaseModel):
    cooling: float = Field(24.0, ge=20.0, le=30.0)  # ge=greater-or-equal
    heating: float = Field(20.0, ge=16.0, le=24.0)

class AgentDecision(BaseModel):
    zone_setpoints: Dict[str, ZoneSetpoint]
    energy_mode: Literal["eco", "balanced", "comfort"]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str

# Usage
d = AgentDecision.model_validate_json('{"zone_setpoints": {...}, ...}')
d.model_dump()              # → Python dict
d.model_dump_json()         # → JSON string
d.model_json_schema()       # → JSON Schema (used for LLM structured output!)
```

**Pydantic Settings (reads from .env automatically):**
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    LLM_MODEL: str = "qwen2.5:7b"
    API_PORT: int = 8000
    SIMULATION_MODE: bool = True
    class Config:
        env_file = ".env"

settings = Settings()   # singleton — used across all modules
```

**Study resource:** https://docs.pydantic.dev/latest/

---

### D. FASTAPI ⭐ IMPORTANT

**What it is:** Modern Python web framework. Auto-generates OpenAPI docs (`/docs`).

```python
from fastapi import FastAPI, HTTPException, WebSocket

app = FastAPI(title="Eco-Loop")

# CORS middleware — allows browser on port 5173 to call API on 8000
app.add_middleware(CORSMiddleware, allow_origins=["*"])

# Startup hook — runs when server starts
@app.on_event("startup")
async def startup():
    await controller.start()    # starts simulation + AI loop

# GET endpoint — returns JSON
@app.get("/api/status")
async def get_status():
    return JSONResponse(content=state_store.get_dashboard_update().model_dump())

# POST with auto-validated body (Pydantic)
@app.post("/api/setpoint")
async def set_setpoint(cmd: SetpointCommand):   # body auto-validated!
    await controller.env.set_setpoint(cmd.zone, cmd.cooling, cmd.heating)

# WebSocket endpoint
@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_json({"type": "update"})

# Mount sub-apps (MCP server, React static files)
app.mount("/mcp", mcp.http_app())
app.mount("/assets", StaticFiles(directory="frontend/dist/assets"))
```

**Study resource:** https://fastapi.tiangolo.com/

---

### E. WEBSOCKETS ⭐ IMPORTANT

**What it is:** Persistent two-way connection between browser and server.
Used to push live building data to dashboard every 2 seconds.

**Server side:**
```python
# backend/dashboard_api.py
class ConnectionManager:
    active: list[WebSocket] = []

    async def connect(self, ws):
        await ws.accept()
        self.active.append(ws)

    async def broadcast(self, data: dict):
        for ws in self.active:
            await ws.send_json(data)    # push to ALL browsers at once
```

**Client side (React custom hook):**
```javascript
// frontend/src/hooks/useWebSocket.js
const ws = new WebSocket('ws://localhost:8000/ws');
ws.onmessage = (event) => {
    setData(JSON.parse(event.data));    // triggers React re-render
};
// Auto-reconnect: retry 1s → 2s → 4s → 8s → max 30s
```

**Key terms:**
- `ws://` vs `wss://` — WebSocket vs WebSocket Secure (TLS)
- **Heartbeat/ping** — keep-alive messages every 20s
- **Exponential backoff** — smart retry strategy on disconnect

---

### F. MCP — MODEL CONTEXT PROTOCOL ⭐ KEY DIFFERENTIATOR

**What it is:** Open standard (Anthropic 2024) letting AI models call external
"tools" in a standardised way. Like USB-C — one plug fits all AI systems.

**Why it matters for Eco-Loop:**
Any MCP-compatible AI (Claude, GPT, Cursor) can control this building
without any code changes — just point it at `/mcp`.

```python
# backend/mcp_server.py
from fastmcp import FastMCP

mcp = FastMCP("Eco-Loop Building Agent")

@mcp.tool()
async def read_building_state() -> dict:
    """Get all zone temperatures, setpoints, energy, comfort."""
    obs = state_store.get_observation()
    return {"zones": {...}, "hvac_power_kw": obs.hvac_power_kw}

@mcp.tool()
async def update_setpoint(zone: str, cooling: float, heating: float) -> dict:
    """Change HVAC setpoints for a specific zone."""
    ok = await controller.env.set_setpoint(zone, cooling, heating)
    return {"success": ok}

# Mount on FastAPI at /mcp
app.mount("/mcp", mcp.http_app())
```

**MCP tools in Eco-Loop (10 total):**
`read_building_state`, `get_hvac_setpoints`, `update_setpoint`,
`update_all_setpoints`, `get_energy_usage`, `calculate_savings`,
`get_comfort_report`, `get_outdoor_conditions`, `get_ai_decision`

**Study resource:** https://modelcontextprotocol.io | https://gofastmcp.com

---

### G. LLM INTEGRATION — OLLAMA + QWEN2.5 ⭐ IMPORTANT

**Ollama:** Run open-source LLMs locally. Like Docker but for AI models.
Provides REST API on `localhost:11434`.

**Qwen2.5-7B:** 7 billion parameter model by Alibaba.
Excellent at structured JSON output and instruction following.

```python
# backend/llm_agent.py
import ollama

client = ollama.Client(host="http://localhost:11434")

# 1. Build prompt with building snapshot table
prompt = """
You are an HVAC control AI. Current building state:
Zone        Temp    Cool_SP  Occ%   PMV
Core        22.3C   24.0C    80%   +0.15
Perimeter_N 21.8C   24.0C    80%   -0.10
Outdoor: 8C | Time: 14:00
Return JSON decision to optimise comfort + energy.
"""

# 2. Call LLM with JSON schema enforcement
response = await client.chat(
    model="qwen2.5:7b",
    messages=[{"role": "user", "content": prompt}],
    format=AgentDecision.model_json_schema(),  # forces valid JSON!
    options={"temperature": 0.3},              # low = deterministic
)

# 3. Parse + validate
decision = AgentDecision.model_validate_json(response.message.content)
```

**Key AI concepts:**

| Term | Meaning |
|---|---|
| **Temperature** | 0.0 = deterministic, 1.0 = creative/random |
| **Structured Output** | Force LLM to return JSON matching a schema |
| **System Prompt** | Instructions given before user message |
| **Context Window** | Max tokens the model can "see" at once |
| **Hallucination** | LLM confidently says something wrong |
| **Fallback** | Rule-based control when LLM unavailable |

**Study resource:** https://ollama.com | https://qwen.readthedocs.io

---

### H. ENERGYPLUS & BUILDING PHYSICS ⭐ DOMAIN KNOWLEDGE

**EnergyPlus:** US DOE's building energy simulation engine.
Takes an IDF (building description) → simulates energy/temperatures for a year.

**IDF file (text format):**
```idf
Zone,
    Core Zone,    !- Name
    ...;

ZoneHVAC:IdealLoadsAirSystem,
    Core Ideal Loads,   !- Simplest HVAC — no real equipment needed
    ...;

EnergyManagementSystem:Actuator,
    Core_Cool_SP,       !- Python API can override this value
    Core Dual Setpoint,
    ThermostatSetpoint:DualSetpoint,
    Cooling Setpoint;
```

**Our physics simulator (SIMULATION_MODE=true):**

**Thermal model equation:**
```
ΔT = Q_total × Δt / thermal_mass

Q_total = Q_solar + Q_people + Q_lighting + Q_equipment + Q_envelope + Q_hvac

thermal_mass = ρ × Cp × Volume × 30
            = 1.204 × 1005 × (400 × 3.5) × 30
            = 50,821,000 J/K  (Core zone)

Why 30×? Real buildings store heat in walls + slab + furniture, not just air.
Air alone = 4 kJ/m²K. With structure = ~120 kJ/m²K.
```

**Key building physics terms:**

| Term | Definition |
|---|---|
| **Thermal Mass** | Heat storage capacity (J/K). High mass → slow temperature change |
| **U-value** | Heat conductance through wall (W/m²K) |
| **UA** | U-value × Area = zone conductance (W/K) |
| **Solar gain** | Heat from sunlight through windows (W/m²) |
| **Deadband** | Temperature range between heating + cooling setpoints |
| **COP** | Coefficient of Performance = heat moved / electricity used |
| **Occupancy** | Fraction of max people present (0=empty, 1=full) |
| **kWh** | Energy (cumulative) |
| **kW** | Power (instantaneous) |

**HVAC control logic in simulator:**
```python
if zone_temp > setpoint_cooling + 0.5:    # too hot → cool
    Q_hvac = -min(MAX_COOLING, Kp × error)
    hvac_kw = abs(Q_hvac) / (COP_cooling × 1000)
elif zone_temp < setpoint_heating - 0.5:  # too cold → heat
    Q_hvac = +min(MAX_HEATING, Kp × error)
else:
    Q_hvac = 0                             # in deadband → HVAC off
```

---

### I. THERMAL COMFORT — PMV / PPD (Fanger Model)

**Standard:** ISO 7730 / ASHRAE Standard 55

**PMV (Predicted Mean Vote):** −3 (very cold) to +3 (very hot). 0 = neutral.
**PPD (Predicted % Dissatisfied):** Minimum 5%, target < 10%.

**Inputs used:**

| Input | Value | Reason |
|---|---|---|
| Metabolic rate | 1.1 met | Sedentary office work |
| Clothing | 0.7 clo | Light office clothing |
| Air velocity | 0.1 m/s | Still air (no draft) |
| Air temp | From simulator | Live |
| Humidity | From weather model | Live |

**Core formula:**
```
PMV = (0.303 × e^(-0.036M) + 0.028) × L
PPD = 100 − 95 × e^(−0.03353×PMV⁴ − 0.2179×PMV²)
```

The solver uses Newton iteration to find clothing surface temperature (`tcl`) first,
then computes the heat load `L`, then `PMV`.

---

### J. REACT + VITE + TAILWINDCSS

**React Hooks used:**
```javascript
// useState — stores data, triggers re-render when changed
const [history, setHistory] = useState([]);

// useEffect — runs side effects after render
useEffect(() => {
    fetch('/api/history').then(r => r.json()).then(d => setHistory(d.entries));
}, []);   // [] = run once on mount

// Custom hook (useWebSocket.js)
export function useWebSocket() {
    const [data, setData] = useState(null);
    const [isConnected, setConnected] = useState(false);
    // WebSocket setup + auto-reconnect logic
    return { data, isConnected, lastUpdate };
}
```

**Component pattern:**
```jsx
export default function MetricCard({ title, value, unit, icon: Icon, color }) {
    return (
        <div className="glass-card hover:shadow-lg transition-all">
            <Icon style={{ color }} />
            <span className="text-2xl font-bold">{value}</span>
            <span className="text-sm text-gray-400">{unit}</span>
        </div>
    );
}
```

**Key React terms:**

| Term | Meaning |
|---|---|
| Props | Data passed from parent to child |
| State | Internal data — changes cause re-render |
| Effect | Code that runs after render |
| JSX | HTML-like syntax in JavaScript |
| Virtual DOM | React's in-memory DOM for efficient updates |
| Hook | Function starting with `use` that uses React features |

**Vite:**
- `npm run dev` → dev server with Hot Module Replacement (instant updates)
- `npm run build` → optimised bundle in `dist/`
- Dev proxy forwards `/api` → FastAPI backend

**TailwindCSS — utility class examples:**
```jsx
<div className="
    bg-gray-900           // dark background
    backdrop-blur-sm      // glassmorphism effect
    border border-white/10  // subtle border
    rounded-xl            // rounded corners
    p-6 m-4              // padding, margin
    hover:shadow-orange-500/25  // glow on hover
    transition-all duration-300 // smooth animation
    grid grid-cols-5 gap-4  // CSS grid layout
">
```

---

### K. CHART.JS

```javascript
// Must register components before using!
import { Chart, LineElement, CategoryScale, LinearScale,
         PointElement, Filler, Tooltip, Legend } from 'chart.js';
Chart.register(LineElement, CategoryScale, LinearScale, PointElement, Filler, Tooltip, Legend);

// Line chart config
const config = {
    type: 'line',
    data: {
        labels: history.map(h => h.sim_time),
        datasets: [{
            label: 'Core Zone',
            data: history.map(h => h.avg_temp),
            borderColor: '#FF6B1A',
            fill: true,
            backgroundColor: 'rgba(255,107,26,0.1)',
        }]
    },
    options: {
        animation: false,              // disable for real-time updates
        responsive: true,
        scales: {
            x: { type: 'time' },       // date-fns adapter handles dates
            y: { min: 15, max: 32 }
        }
    }
};
```

---

### L. DOCKER & DOCKER COMPOSE

**Dockerfile:**
```dockerfile
FROM python:3.11-slim       # base image
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./backend/
EXPOSE 8000
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

**docker-compose.yml:**
```yaml
services:
  ollama:
    image: ollama/ollama:latest
    ports: ["11434:11434"]
    volumes: [ollama_data:/root/.ollama]  # persist model downloads

  eco-loop:
    build: .
    depends_on: [ollama]               # waits for ollama to be ready
    environment:
      OLLAMA_HOST: http://ollama:11434  # service discovery by name!
      SIMULATION_MODE: "true"
    ports: ["8000:8000"]
```

**Commands:**
```bash
docker build -t eco-loop .             # build image
docker-compose up --build              # start all containers
docker-compose logs -f eco-loop        # follow logs
docker ps                              # list running containers
docker-compose down                    # stop + remove containers
```

---

### M. CLEAN ARCHITECTURE PATTERNS USED

**Singleton — `state.py`**
One shared instance of state store across all modules.
```python
state_store = BuildingStateStore()   # created once at module level
```

**Abstract Base Class — `energyplus_runner.py`**
Interface that both real EnergyPlus and simulator implement.
```python
class BuildingEnvironment(ABC):
    @abstractmethod
    async def step(self) -> BuildingObservation: ...

class SimulatedBuildingEnvironment(BuildingEnvironment):
    async def step(self): ...    # concrete implementation
```

**Factory Function:**
```python
def create_environment() -> BuildingEnvironment:
    if settings.SIMULATION_MODE:
        return SimulatedBuildingEnvironment()   # swap without changing callers
    return EnergyPlusEnvironment()
```

**Observer / Broadcast:**
State changes → broadcast to all WebSocket subscribers (dashboard browsers).

---

## 4. FULL DATA FLOW — STEP BY STEP

```
Every 15 sim-minutes (0.25s wall-clock at 60× speedup):

1. SimulatedBuildingEnvironment._step_sync()
   ├── weather.get_conditions(sim_time) → outdoor_temp, humidity
   ├── occupancy.get(sim_time) → 0.0–1.0
   ├── For each of 5 zones:
   │   ├── Q_solar    = solar_wpm2(zone, time) × area
   │   ├── Q_people   = 75W × area × 0.07 ppm × occupancy
   │   ├── Q_lighting = 9 W/m² × area
   │   ├── Q_equipment= 10 W/m² × area × (0.3 + 0.7×occ)
   │   ├── Q_envelope = -UA × (zone_temp − outdoor_temp)
   │   ├── Q_hvac     = proportional_control(temp, sp_cool, sp_heat)
   │   ├── dT = Q_total × 900s / 50,821,000 J/K
   │   ├── zone_temp += dT + gaussian_noise(0, 0.02)
   │   └── pmv, ppd = fanger(zone_temp, humidity, met=1.1, clo=0.7)
   └── Returns BuildingObservation

2. state_store.update_observation(obs)
   └── Thread-safe write (RLock)

3. broadcast_loop() [every 2 seconds]
   ├── Reads state_store (thread-safe read)
   ├── Builds DashboardUpdate dict
   └── ws.send_json(data) to every connected browser

4. Every 30 seconds: AI agent wakes
   ├── Read observation + last 20 history entries
   ├── Build prompt (zone table, outdoor, time, energy)
   ├── POST http://localhost:11434/api/chat
   │   → model: qwen2.5:7b
   │   → format: AgentDecision JSON schema
   │   → temperature: 0.3
   ├── Parse AgentDecision from JSON response
   ├── Validate: setpoints within safe bounds
   ├── env.set_setpoint(zone, cool, heat) for all 5 zones
   └── state_store.update_decision(decision)

5. Browser (React)
   ├── useWebSocket() receives JSON every 2s
   ├── setData() → triggers re-render
   ├── MetricCard → avg temp, HVAC power, comfort %, savings %, CO2
   ├── AIDecisionPanel → LLM reasoning, mode badge, zone setpoints
   ├── TemperatureChart → 5-zone line chart (Chart.js)
   ├── EnergyChart → actual vs baseline area chart
   ├── ComfortGauge → SVG PMV gauge + PPD %
   └── ZoneGrid → 5-zone status table
```

---

## 5. KEY NUMBERS

| Metric | Value | Explanation |
|---|---|---|
| Simulation timestep | 15 min | EnergyPlus standard |
| Speedup factor | 60× | 1 sim-day = 24min/60 = 24s wall-clock |
| Agent interval | 30 s | LLM decision every 30s |
| WS broadcast | 2 s | Dashboard refresh rate |
| Thermal mass multiplier | 30× | Walls+slab+furniture vs air |
| Core thermal mass | 50,821 kJ/K | Realistic for concrete office |
| Internal gains (Core) | ~9,700 W | At full occupancy |
| HVAC sizing | 80 W/m² cooling | Standard VAV |
| Energy savings | 16.9% | vs fixed-setpoint baseline |
| Peak demand reduction | 21.6% | Avoids utility demand charge |
| CO₂ saved/year | ~930 kg/building | At 0.233 kg CO₂/kWh |
| PMV comfort target | −0.5 to +0.5 | ASHRAE 55 |
| PPD target | < 10% | ASHRAE 55 |
| Zones | 5 | Core + N/S/E/W perimeter |
| MCP tools | 10 | Sensors + actuators |

---

## 6. INTERVIEW / PRESENTATION Q&A

**Q: Why use a local LLM instead of GPT-4 / Claude?**
A: Privacy (building data stays on-premise), zero API cost, no internet needed,
works in air-gapped industrial environments. Honeywell customers won't send
proprietary building data to cloud providers.

**Q: What happens if Ollama crashes?**
A: Automatic fallback to rule-based controller. Checks occupancy + time of day,
selects eco/balanced/comfort mode deterministically. Dashboard shows "LLM unavailable"
but HVAC control continues uninterrupted.

**Q: What is MCP and why does it matter?**
A: Model Context Protocol is an open standard for AI tool access. By exposing
building controls as MCP tools, any future AI system can control this building
without code changes. It makes the building "AI-native" and interoperable.

**Q: Why EnergyPlus instead of a simple model?**
A: EnergyPlus is the DOE industry standard used by architects and engineers.
It validates our work is physically realistic. Our physics fallback uses the same
equations (thermal mass, Fanger PMV) so results are credible either way.

**Q: What was the thermal mass bug and how did you fix it?**
A: The original simulator only counted air in the thermal mass calculation,
giving ~1,695 kJ/K for the Core zone. This caused temperatures to spike 6–8°C
per 15-minute step (unrealistic). Real buildings store heat in walls, concrete
slabs, and furniture. Adding a 30× multiplier gives ~50,821 kJ/K and
a realistic 0.17°C/step drift.

**Q: Why asyncio instead of regular threading for the backend?**
A: The simulation loop, AI agent loop, and WebSocket broadcast are all I/O-bound
(sleeping, HTTP calls, network writes). asyncio lets them share one thread via
cooperative multitasking — much lighter than OS threads. The only real thread
is used for EnergyPlus API callbacks which must run in a separate thread.

---

## 7. STUDY ROADMAP (Priority Order)

### Week 1 — Python Core
1. `async`/`await`/asyncio — work through Python docs tutorial
2. Pydantic v2 — build models, validate JSON, use Field constraints
3. FastAPI — build a small API with GET/POST endpoints + Swagger

### Week 2 — AI Layer
1. Install Ollama locally, pull `qwen2.5:7b`, test in terminal
2. Use `ollama` Python client, get structured JSON output
3. Understand temperature, system prompts, context windows, hallucinations
4. Read FastMCP quickstart, build a simple tool

### Week 3 — Building Physics
1. EnergyPlus Getting Started guide (free PDF, US DOE)
2. Thermal mass, U-values, solar gain, HVAC sizing basics
3. ASHRAE 55 standard — comfort zones, PMV/PPD explanation
4. Fanger model — what each input variable means

### Week 4 — Frontend
1. React official tutorial (react.dev) — hooks, components, props
2. Vite docs — understand dev server, HMR, build output, proxy
3. TailwindCSS — utility classes, responsive grid, dark mode
4. Chart.js — register components, line/area charts, real-time update pattern

### Ongoing — Architecture
1. Design patterns: Singleton, Abstract Base Class, Factory, Observer
2. Thread safety — locks, race conditions, why they matter
3. Docker — build, run, compose, networking between containers

---

## 8. ALL STUDY LINKS

| Topic | URL |
|---|---|
| asyncio | https://docs.python.org/3/library/asyncio.html |
| Pydantic v2 | https://docs.pydantic.dev/latest/ |
| FastAPI | https://fastapi.tiangolo.com/ |
| FastMCP | https://gofastmcp.com/ |
| MCP Specification | https://modelcontextprotocol.io |
| Ollama | https://ollama.com |
| Qwen2.5 | https://qwen.readthedocs.io |
| EnergyPlus Docs | https://energyplus.net/documentation |
| ASHRAE 55 | https://www.ashrae.org/technical-resources/bookstore/standard-55 |
| Fanger PMV | https://en.wikipedia.org/wiki/Predicted_mean_vote |
| React | https://react.dev/ |
| Vite | https://vitejs.dev/ |
| TailwindCSS | https://tailwindcss.com/docs |
| Chart.js | https://www.chartjs.org/docs/latest/ |
| Docker | https://docs.docker.com/get-started/ |
| python-pptx | https://python-pptx.readthedocs.io |

---

## 9. REPO STRUCTURE QUICK REF

```
honeywell hack/
├── run.py                       ← Start here. Single launcher.
├── requirements.txt             ← pip install -r requirements.txt
├── .env.example                 ← copy to .env
├── docker-compose.yml           ← full stack in containers
├── Dockerfile                   ← backend container
├── README.md                    ← full documentation
├── LICENSE                      ← MIT
│
├── config/settings.py           ← ALL config (env-var driven)
│
├── backend/
│   ├── models.py                ← Pydantic data models (read first)
│   ├── state.py                 ← thread-safe shared state
│   ├── energyplus_runner.py     ← simulation engine (biggest file)
│   ├── llm_agent.py             ← Ollama/Qwen2.5 + rule fallback
│   ├── mcp_server.py            ← FastMCP 10 tools
│   ├── controller.py            ← autonomous control loop
│   ├── dashboard_api.py         ← WebSocket manager
│   └── app.py                   ← FastAPI main app
│
├── energyplus/building.idf      ← 5-zone office model (text)
│
├── frontend/
│   ├── package.json             ← npm dependencies
│   ├── vite.config.js           ← build + dev proxy
│   ├── tailwind.config.js       ← custom theme
│   └── src/
│       ├── main.jsx             ← React entry point
│       ├── App.jsx              ← main layout + data wiring
│       ├── hooks/useWebSocket.js ← WS + auto-reconnect
│       └── components/
│           ├── MetricCard.jsx
│           ├── AIDecisionPanel.jsx
│           ├── TemperatureChart.jsx
│           ├── EnergyChart.jsx
│           ├── ComfortGauge.jsx
│           ├── ZoneGrid.jsx
│           └── SavingsCounter.jsx
│
├── docs/demo_script.md          ← 3-min video script
├── presentation/slides.md       ← 10-slide deck content
└── Eco_Loop_Submission.pptx     ← hackathon submission file
```

---

*Study this alongside the actual source code.*
*GitHub: https://github.com/Arnavshukla09/Eco_Loop_Building_Agents*
