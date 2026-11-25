# Seasonal benchmark

Synthetic weather; identical per-season seeds and initial conditions. Comfort includes occupied samples only. Fan energy and configurable time-of-use cost are included. LLM source counts identify fallback explicitly.

| Season | Seed | Controller | kWh | Cost | Occupied comfort % | Peak kW |
|---|---|---|---|---|---|---|
| winter | 42 | fixed | 164.295 | 20.8335 | 80.44 | 19.47 |
| winter | 42 | scheduled | 100.459 | 13.2978 | 78.22 | 22.19 |
| winter | 42 | rule_based | 128.475 | 16.1629 | 81.33 | 31.19 |
| winter | 42 | forecast | 111.101 | 13.5049 | 83.11 | 30.19 |
| winter | 42 | llm | unavailable | — | — | — |
