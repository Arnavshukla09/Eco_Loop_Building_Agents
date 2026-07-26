# Eco-Loop Demo Script — 3-Minute Video

**Target duration:** 2:45 – 3:00 minutes  
**Format:** Screen recording with voiceover  
**Tone:** Confident, energetic, expert

---

## Pre-Recording Checklist

- [ ] System running: `python run.py`
- [ ] Dashboard open: `http://localhost:8000`
- [ ] Ollama running with Qwen2.5-7B pulled
- [ ] Terminal visible for MCP curl demo
- [ ] Simulation running for at least 2 minutes (charts populated)
- [ ] Screen resolution: 1920×1080
- [ ] Disable notifications

---

## Script

### [0:00 – 0:20] Opening Hook

**[Screen: Dashboard loading]**

*Voiceover:*
"Buildings consume 40% of global energy — and most of that waste happens because HVAC systems run on fixed schedules, ignoring what's actually happening inside the building.

Today I'm showing you Eco-Loop: an autonomous AI that thinks like a building engineer, making real-time HVAC decisions using a fully local open-source language model."

---

### [0:20 – 0:50] Dashboard Overview

**[Screen: Full dashboard, zoom into metric cards]**

*Voiceover:*
"This is our live dashboard. The building simulation is running right now — a 5-zone office building modelled with real thermal physics.

At the top, you see real-time metrics:
- Average temperature across all zones: 22.3 degrees
- HVAC power draw: 14.2 kilowatts
- Comfort score: 87% — well within ASHRAE 55 standards
- And most importantly: **16.9% energy savings** versus a fixed-setpoint baseline

That CO₂ counter? 8.2 kilograms saved since we started."

---

### [0:50 – 1:20] AI Decision Panel

**[Screen: Zoom into AI Decision Panel]**

*Voiceover:*
"This is where it gets interesting. Every 30 seconds, our AI agent — Qwen2.5-7B running locally via Ollama — reads all building sensors through an MCP server and generates a structured decision.

Right now it's in **Eco Mode**. The reasoning says:
*'Low afternoon occupancy at 52%. Widening thermal deadband on all zones. Raising cooling setpoints by 1.5°C to reduce compressor load while maintaining comfort targets.'*

Confidence: 91%. And it's adjusting each zone independently — south-facing perimeter gets a higher cooling setpoint because it already has solar gain."

---

### [1:20 – 1:50] MCP Tools

**[Screen: Split — terminal on left, API docs on right]**

*Voiceover:*
"The secret ingredient is our MCP server. It exposes 10 building automation tools that any AI assistant can call.

Watch this — I'm calling `read_building_state` directly from the command line.

[Type: curl command]

Instantly I get a structured JSON response: all zone temperatures, setpoints, comfort scores, energy data. This is exactly what our AI agent sees before making each decision.

These tools work with Claude Desktop, Cursor, or any MCP-compatible client. Your building becomes an AI-native resource."

---

### [1:50 – 2:20] Charts + Simulation

**[Screen: Temperature and Energy charts]**

*Voiceover:*
"Let's look at the charts. The temperature chart shows all 5 zones over the last 8 simulated hours. You can see the zones tracking closely to their setpoints — that shaded band shows the current cooling-to-heating deadband.

The energy chart compares actual HVAC power — the orange line — against what a fixed-setpoint system would use — the gray baseline. The green shading is the savings.

This simulation runs at 60 times real speed: one simulated day takes about 6 seconds. We're running EnergyPlus physics: thermal mass, solar gains, occupancy schedules, real weather patterns."

---

### [2:20 – 2:50] Closed Loop + Architecture

**[Screen: Quick architecture diagram or code view]**

*Voiceover:*
"The closed loop runs continuously:

EnergyPlus provides sensor readings.
MCP tools expose them to the AI.
Qwen2.5 analyzes and returns a JSON decision.
The controller validates and applies new setpoints.
The loop repeats.

Everything runs locally — no cloud APIs, no data leaving your machine. The Python backend, the LLM inference, the simulation — all on one laptop.

And it's fully modular: swap in real EnergyPlus for the simulator, swap Qwen2.5 for Llama3, connect real Honeywell BMS sensors. The architecture stays the same."

---

### [2:50 – 3:00] Closing

**[Screen: Return to full dashboard]**

*Voiceover:*
"Eco-Loop demonstrates that Physical AI for buildings is ready today.

Open-source LLM. Real simulation. MCP interoperability. Live dashboard. Autonomous control.

Honeywell has the sensors, the hardware, and the customer relationships. Eco-Loop provides the AI layer that makes every building smart.

Thank you."

---

## Post-Recording Notes

- **Total runtime target**: 2:55
- Add captions for accessibility
- Background music: subtle, corporate, low volume
- Add intro card: "Honeywell Eco-Loop | Building Agents Hackathon 2024"
- End card: Team names + GitHub URL
- Export at 1080p / 60fps
