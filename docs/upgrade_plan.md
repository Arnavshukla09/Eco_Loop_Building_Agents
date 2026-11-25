# Ordered upgrade plan

Date: 2026-11-25. Builds on the completed correction work.

| Order | Work | Acceptance check |
|---|---|---|
| 1 | Generate a complete five-zone EnergyPlus model; add model checks and an explicit real-engine smoke command | All zones have geometry, constructions, loads, ventilation, HVAC, thermostats, and runtime outputs; engine results recorded if installed |
| 2 | Add seasonal, multi-day evaluation against fixed and scheduled baselines | Identical seeds/weather; occupied comfort, cost, peak, fan energy, inference counts and latency reported |
| 3 | Add forecast/tariff-aware supervisory control and evaluate live LLM separately | Explicit model availability; no fallback result presented as LLM success |
| 4 | Implement fan/ventilation behavior and timed manual overrides | Fan consumption affects total energy; occupancy ventilation minimum enforced; held zones protected until expiry or release |
| 5 | Add dashboard control status, requested/applied decisions, run comparison, history replay/export | Saved runs can be selected and inspected without changing live control |
| 6 | Add monitor-only BACnet/Modbus adapters and deployment/reproducibility checks | Explicit configured point maps; no hardware writes; protocol unit coverage; dependency lock, migrations, Docker/browser CI |
| 7 | Refresh project documentation and demonstration material | Claims correspond to fresh validation evidence; external integration gates clearly recorded |

Implementation follows dependency order, with fan and control telemetry established
before final benchmark runs and dashboard integration. Physical device commissioning
requires a reachable device and its point map; the implementation defaults to no
device network activity. Existing README work is preserved and extended in place.

## Execution record

Implementation completed locally on 26 November 2026, with integration limits recorded separately from software completion:

| Work | Implemented result | Evidence and remaining scope |
|---|---|---|
| Five-zone EnergyPlus model | Reproducible geometry, envelope, gains, ventilation, IdealLoads HVAC, thermostats, and runtime output generation in `energyplus/generate_model.py` | [Real-engine smoke result](validation/energyplus_smoke.json) checks stepping and a Core thermostat update. It does not establish an annual run, calibrated electrical metering, fan actuation, or complete physical fidelity. |
| Seasonal comparisons | `benchmark.py` compares fixed, scheduled, rule-based, and forecast control with matched seeded synthetic conditions | [Seasonal report](validation/seasonal_benchmark.md) and [raw configuration/results](validation/seasonal_benchmark.json). Occupied comfort, cost, peak demand, and fan electricity are reported; synthetic results are not field performance. |
| Forecast/tariff and LLM control | Explicit heuristic forecasts and time-of-use prices; configured model availability and decision-source attribution | [Saved LLM comparison](validation/llm_comparison.json). Run-specific availability, fallback counts, and latency must accompany any LLM claim. |
| Fans and timed holds | Fan consumption/ventilation in the Python simulator; manual zone holds expire in simulation time or release explicitly | Backend regression and browser tests; real EnergyPlus fan changes remain unsupported, and physical hardware writes remain absent. |
| Dashboard history | Provider/hold status, requested versus acknowledged setpoints, archived run summaries, replay, and CSV export | Chromium and Firefox E2E passed locally; see the [current audit](project_audit_2026-11-26.md) for exact coverage and evidence. |
| Hardware and reproducibility | Explicit monitor-only Modbus/BACnet point readers, additive migrations, dependency lock, hardened Docker configuration, and browser/security CI jobs | Protocol tests use doubles. Device commissioning, PostgreSQL integration, and Docker runtime checks require their target environments. Remote CI status must be verified after publishing. |
| Documentation | Current README and dated audit linked from archived study, evaluation, and submission material | [Current audit and before/after report](project_audit_2026-11-26.md). Original PDF/PPTX remain unchanged archival artifacts. |

Local implementation and test completion do not imply that a public deployment, physical building, container image, or remote GitHub workflow has been verified. The current audit is authoritative for those statuses.
