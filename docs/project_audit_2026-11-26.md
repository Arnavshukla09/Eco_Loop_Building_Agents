# Project audit and release validation â€” 26 November 2026

The local project has been audited, patched, and validated as an engineering simulation prototype. The final locked Python environment passes **140 backend tests**, the frontend passes **7 unit tests**, and the production dashboard passes **16 E2E tests across Chromium and Firefox**. Both dependency audits report **zero known vulnerabilities**. Real EnergyPlus 24.1 stepping and thermostat feedback pass a separate smoke test.

This report compares the published revision, the unpublished work present at the start of this task, and the patched result. It does not certify a physical building, annual savings, or an internet deployment. GitHub publication was verified: remote `main` matched `f29b415f27cfcddc628d5d9b2e0cdb37af0f85b3`, and [CI run 45685980422](https://github.com/Arnavshukla09/Eco_Loop_Building_Agents/actions/runs/45685980422) completed successfully for that revision. Backend/security checks, frontend build/tests, and production Chromium/Firefox E2E all passed. This confirmation is added in a subsequent documentation commit; the live workflow remains the authority for each later revision.

## Scope and starting state

- Repository: [Arnavshukla09/Eco_Loop_Building_Agents](https://github.com/Arnavshukla09/Eco_Loop_Building_Agents), public, default branch `main`.
- Published starting commit: `20eedfe756e41cc89fdb87913dace8d02dd66984`, preceded by 14 other published commits.
- The initial worktree contained 29 modified tracked files and numerous new implementation, benchmark, test, and documentation files. Those changes were preserved and incorporated rather than discarded.
- A recoverable starting worktree ZIP, binary diff, status, and metadata were saved locally under `.tools/audit-2026-11-26/`. These contain project source and remain ignored runtime material.
- Platform: Windows, Python 3.11.15, Node 24.14.0, npm 11.9.0. User-facing dates use Asia/Calcutta. Evidence timestamps retain their original UTC representation; 25 November UTC executions here occurred on 26 November IST.
- Reviewed areas: backend/controller, REST and MCP transport/authentication, WebSockets, simulation and EnergyPlus adapter/model, forecast/tariffs/fans/manual holds, persistence/migrations, monitor-only hardware adapters, frontend/components/charts, launcher, dependencies, Git history, Docker/Compose, CI, and documentation claims.

No physical device networks were contacted. Browser tests used isolated authenticated simulator processes and new SQLite databases. Existing saved building runs were not reset by browser tests.

## Before and after

| Area | Published / starting evidence | Patched evidence |
|---|---|---|
| Published backend tests | Isolated export of `20eedfe`: **54 passed, 1 failed** with the current environment. The corrupted-response test selected rule control before reaching its intended malformed-response path. | **140 passed**, including **43 new audit regressions** and **16 launcher/evaluation regressions**, in a fresh environment installed from `requirements.lock`. |
| Starting unpublished backend tests | **81 passed** once pytest temporary storage was moved inside the workspace. The first default-temp attempt produced permission errors, which are not counted as application test failures. | Isolated fixtures, explicit regression coverage, and reproducible command recorded below. |
| GitHub workflow | Published [CI run 41067825932](https://github.com/Arnavshukla09/Eco_Loop_Building_Agents/actions/runs/41067825932) failed in **Backend Tests / Run pytest**; frontend build passed. | Workflow installs locked dependencies, audits dependencies/security, runs backend tests, builds/tests frontend, and runs both browser engines. All three jobs passed at published revision `f29b415`; see the [saved remote result](validation/audit-2026-11-26/github-release-validation.json). |
| Browser testing | Playwright dependency existed without a configured repeatable E2E suite. | **16/16 passed**, zero unexpected, skipped, or flaky tests. Production build and a clean locked backend were used. |
| Frontend regression tests | Five existing telemetry checks. | **7/7 passed**; includes preserving missing measurement gaps. |
| Network/security defaults | API/MCP bound to all interfaces, wildcard CORS, development control permitted without a key. | Loopback defaults, explicit origins, browser mutation/WS origin guard, production key requirement, hardened container configuration. |
| Energy results | Historical README/root report claimed **45.62%** savings and **8.87%** peak reduction under the earlier model. Evaluation copied actuation logic and omitted requested fan operation. | Shared controller actuation, fan energy included: **36.34% Â± 0.92%** mean energy savings, **7.98% increase** in peak demand, **63.1% Â± 0.4%** all-zone PMV target adherence in the refreshed 24-hour scenario. These model versions are not interchangeable. |
| Evidence integrity | Historical tables mixed old start times, inference results, and obsolete limitations. Some zone-temperature history was randomly synthesized from building averages. | Current evidence linked; prior unpublished benchmark artifacts archived under `validation/history/2026-11-25/`; missing zone measurements render gaps. Historical submission documents are labelled archival. |

The published test comparison uses today's environment, not the original dependency resolution from October. Its result therefore diagnoses present reproducibility, not the state of the author's original machine.

## Findings and resolutions

Severity reflects plausible impact in this prototype's deployment, not a formal penetration-test score. All implemented fixes below have targeted regressions or direct integration evidence.

| ID | Severity | Before | Resolution and verification |
|---|---|---|---|
| SEC-01 | High | Untrusted websites could attempt simple POST controls against a development server; CORS headers alone do not prevent side effects. Same-host trust also permitted a DNS-rebinding route. | `backend/auth.py` and origin middleware reject untrusted browser mutations, MCP calls, and WS handshakes. Host headers cannot establish trust for arbitrary remote names. Exact configured origins and loopback same-origin are covered. |
| SEC-02 | High | Compose exposed development control and Ollama on all host interfaces without requiring a key. | Loopback host port mappings, production authentication, mandatory Compose `API_KEY`, nonroot runtime user, and explicit writable data paths. Static configuration reviewed; container execution remains unverified. |
| SEC-03 | Medium | MCP accepted API keys in URL query parameters, exposing credentials to URL logs/history. | Bearer transport headers only; UTF-8 constant-time comparisons; HTTP authentication context propagates to tools. Query-key rejection and authenticated MCP protocol calls tested. |
| SEC-04 | Medium | A misspelled environment could silently avoid production fail-closed behavior. | Settings restrict valid environment values; production/missing-key and wrong-key cases tested. |
| SEC-05 | Medium | Dashboard API token remained in persistent localStorage. | Uses tab-scoped sessionStorage and removes the old localStorage entry. Browser assertions verify behavior. Same-origin script access remains inherent to this prototype's token design. |
| DATA-01 | High | Decision audit records could lose the distinction between requested setpoints, slew-limited applied values, held zones, rejected zones, and queued EnergyPlus commands. | Requested/applied payloads retained separately through additive migration v3; held/partial/failed/queued status recorded; failed actuators do not suppress independent zones. |
| DATA-02 | Medium | Nonfinite raw sensor values survived imputation and could fail strict REST JSON serialization. | NaN and both infinities are sanitized for serialized telemetry; API regression tests pass. |
| DATA-03 | Medium | A failed reference after reset could leave stale baseline data and incorrect measured-savings attribution. | Invalidates mismatched baseline data and run classification; synchronized seed/reset/reference tests pass. |
| DATA-04 | Medium | `TemperatureChart` generated absent per-zone history with `Math.random()`. Repeated initial-history loads could replace newer live samples. | Only measured zone readings render; missing readings remain gaps. Initial and streamed history merge chronologically with deduplication. |
| CTRL-01 | Medium | Health mode ignored selected deterministic providers or actual fallback; manual hold default ignored its setting. | Reports actual source and degraded fallback; `MANUAL_OVERRIDE_MINUTES` supplies request defaults. All four provider/fallback modes covered. |
| CTRL-02 | Medium | EnergyPlus timestamps used ambiguous minute/current-time values that drifted after an actuator change. | Computes discrete zone clock from hour, zone timestep index, and zone duration. Real feedback test confirms exactly 15 minutes between steps and Core 26/18Â°C acknowledgement. |
| CTRL-03 | Medium | Forecasts discarded fractional hours; invalid hardware mappings/nonfinite scaled values were insufficiently checked. | Forecast expectation matches the weather model without consuming its RNG. BACnet/Modbus mapping, scaling, nonfinite, and cleanup regressions use test doubles. |
| UI-01 | Medium | Text `pong` heartbeat was parsed as JSON; WebSocket URL bypassed proxy configuration; stale socket handlers interfered with reconnects. | Same-origin WS routing, heartbeat handling, socket identity/cleanup checks. Browser suite waits through heartbeat and exercises reconnection. |
| UI-02 | Medium | Structured FastAPI 422 errors could render objects in React; failed release/history requests were unhandled or appeared empty. | Normalized readable errors, visible network errors/retry, cleared replay state on run changes. Both browser engines exercise these paths. |
| UI-03 | Low | Negative savings looked positive and comfort labeling implied ASHRAE compliance. | Signs/colors reflect measured penalties; comfort is labelled a PMV target rather than certification. |
| RUN-01 | Medium | Windows launcher could fail on Unicode output or npm resolution, reuse stale builds, claim rule-only operation while probing an LLM, and loosely match model tags. | UTF-8 output, resolved `npm.cmd`, lock-aware `npm ci`, fresh builds, fail-fast checks, exact host-aware model check, Python 3.11 minimum, true `--sim-only` rule provider. Windows subprocess regression and actual check pass. |
| EVAL-01 | Medium | Evaluation duplicated safety actuation and excluded fan decisions; fixed display strings overstated scope/transport performance. | Uses `AutonomousController._apply_decision`, preserves measured snapshots, reports actual duration/model/start, removes unmeasured transport estimates. New matched evidence includes the peak-demand penalty. |
| BUILD-01 | Medium | Docker and CI installed unbounded requirements; host build artifacts could enter the Docker context; browser/security checks were absent. | Lockfile installation, `.dockerignore`, Node 24, frontend unit/build and Chromium/Firefox E2E jobs, least-privilege workflow token, dependency audits, medium/high Bandit gate. Clean local dependency installation passes. |

## Executed validation

| Check | Result | Evidence |
|---|---|---|
| Published revision test export | 54 pass / 1 fail | [Published JUnit](validation/audit-2026-11-26/published-head-tests.xml) |
| Starting unpublished suite | 81 pass | [Starting JUnit](validation/audit-2026-11-26/initial-tests.xml) |
| Fresh locked Python installation | 104 packages installed; dependency compatibility passes | `uv venv .tools/release-venv` then `uv pip install -r requirements.lock`; no audit tooling required in release environment |
| Final backend suite | **140 pass**, 1 Starlette/httpx deprecation warning | [Final JUnit](validation/audit-2026-11-26/final-backend-tests.xml) |
| Frontend clean install/unit/build | `npm ci` succeeds; **7 pass**; production Vite build succeeds | [Unit output](validation/audit-2026-11-26/frontend-unit-tests.txt); production build is also a prerequisite of the browser run |
| Browser E2E | **8 Chromium + 8 Firefox pass**, 77.668 seconds, no skips/flakes/failures | [Machine report](validation/audit-2026-11-26/e2e-results.json), [desktop](validation/audit-2026-11-26/dashboard-desktop-chromium.png), [mobile](validation/audit-2026-11-26/dashboard-mobile-chromium.png) |
| Python installed-package audit | Zero known advisories | [pip-audit environment result](validation/audit-2026-11-26/python-audit.json) |
| Locked Python dependency audit | Zero known advisories | [Locked dependency result](validation/audit-2026-11-26/locked-dependency-audit.json) |
| npm audit | Zero advisories at every severity | [npm result](validation/audit-2026-11-26/npm-audit.json) |
| Bandit application scan | **0 high / 0 medium**, 11 low heuristic findings | [Full unsuppressed result](validation/audit-2026-11-26/bandit-final.json) |
| Credential pattern scan | No matches in worktree or all 15 published commits / 700 text blobs | [Worktree](validation/audit-2026-11-26/secret-scan.json), [history](validation/audit-2026-11-26/history-secret-scan.json); limited to private-key/GitHub/OpenAI/AWS formats |
| Real EnergyPlus 24.1 | Five zones observed, two steps, thermostat update acknowledged, correct zone clock | [Engine result](validation/energyplus_smoke.json) |
| 24-hour matched evaluation | Three seeds; all ten MCP functions successful at 50 repetitions each; injected faults recovered | [Evaluation](validation/evaluation_report.md), [JSON](validation/evaluation_results.json) |
| Seasonal evaluation | **48 scenarios / 32,256 timesteps**: four seasons Ã— three seeds Ã— four control modes Ã— seven days | [Seasonal report](validation/seasonal_benchmark.md), [JSON](validation/seasonal_benchmark.json) |
| Live LLM comparison | Configured `qwen2.5:1.5b` unavailable; result explicitly omitted | [Comparison](validation/llm_comparison.md), [JSON](validation/llm_comparison.json) |
| Published GitHub validation | **All three jobs successful** at `f29b415`; remote branch hash verified | [Remote result](validation/audit-2026-11-26/github-release-validation.json), [live run](https://github.com/Arnavshukla09/Eco_Loop_Building_Agents/actions/runs/45685980422) |
| Launcher and repository integrity | Windows rule-only `--check` passes; Git object check and whitespace checks pass | [Launcher output](validation/audit-2026-11-26/launcher-check.txt) |

Browser coverage includes telemetry/heartbeat, absent/wrong credentials, scoped manual hold and release, reconnect, release-network failure/retry, invalid deadband and structured validation errors, reset/archive/replay/CSV download, history failure recovery, and mobile overflow. Per-zone input values and actual acknowledged state are verified. Both engines run the same eight scenarios against a production build.

Bandit's remaining low findings are retained for review: seeded simulation RNG (3), controlled subprocess imports/calls (3), an assertion in an injected-fault verification path (1), and best-effort exception branches (4). None is silently excluded from the saved scan. Persistence failures are logged but are not yet part of health readiness, as noted below. A zero advisory count is a statement about the queried databases and versions, not proof that vulnerabilities cannot exist.

## Benchmark interpretation

The refreshed 24-hour run starts at `2024-01-01T08:00:00`, uses 96 Ã— 15-minute steps and seeds 42/101/2024, and compares fixed 22/21Â°C reference control against deterministic rule-based control. Mean baseline consumption is **160.90 kWh**, controlled consumption **102.41 kWh**, energy savings **36.34%**, and avoided emissions **22.58 kg** using the stated 0.386 kg/kWh factor. Mean peak-demand reduction is **-7.98%**, meaning an increase. Comfort target adherence improves from **50.9% to 63.1%** across all sampled zones/times. Occupied-only comfort is separately reported in seasonal results.

The seven-day seasonal study reports matched mean energy savings of **26.44% scheduled**, **18.38% rule-based**, and **25.94% forecast**, with occupied PMV target adherence averaging **81.08%, 80.18%, and 89.10%**, respectively. These averages span twelve season/seed pairs; they are not universal performance guarantees. Heuristic forecasting is not a formally optimized MPC controller.

The actual LLM was unavailable in this session. Historical inference evidence remains under the dated history folder and must not be presented as current successful inference. The batch evaluator uses synchronous inference for offline scenarios, while the application provider uses async inference; batch latency does not establish application throughput.

EnergyPlus uses IdealLoads thermal delivery and stated COP assumptions to estimate electrical consumption. Its humidity/occupancy and fan behavior do not establish calibrated real-building metering. The smoke test demonstrates engine integration and feedback, not annual or field validation.

## Remaining limitations and follow-up work

| Item | State / next action |
|---|---|
| Docker runtime | Docker executable unavailable on this Windows host. Configuration parsed/reviewed, image not built or launched. Run `docker compose config`, build, and authenticated smoke tests on a Docker-enabled host. HTTP container healthcheck currently proves liveness, not database/auth readiness. |
| PostgreSQL | SQLite integration/migrations tested. PostgreSQL driver/service integration unexecuted; install/configure `asyncpg` and validate migrations/transactions against an actual service before selecting it. |
| Persistence health | The simulator intentionally continues when persistence fails; logs warn, but `/api/health` does not expose database health. Add explicit persistence readiness/alerting before operations depend on durable audit records. |
| Physical BACnet/Modbus | Monitor-only adapters tested with doubles; optional driver requirements are ranges and are not part of the reproduced base lock. Commission a dedicated driver environment and verified point map against authorized devices. No physical writes are implemented. |
| LLM | Install/serve the configured model and rerun the explicit LLM comparison. Current savings belong to deterministic controllers. |
| Public deployment | GitHub source publication is distinct from a hosted application. GitHub Pages is disabled and no production URL is configured. TLS/reverse proxy, user roles, read-data authorization and operational limits require a deployment design. Public REST telemetry/history and trusted-origin WS reads are intentional here. |
| Physics and comfort | Synthetic weather, fixed assumptions, PMV proxy and fan model require calibration. Annual weather-driven validation and occupied-building safety certification remain external work. |
| Runtime warnings | Starlette warns about the httpx test transport. Tests pass; migrate when the dependency's replacement transport is adopted. |
| Archived submission | Original PDF/PPTX, historical root reports, study guide and demo/slide source are preserved. Their historical claims do not override this report. |

## Reproduction

Use Python 3.11 and Node 24. Install the repository lockfiles in an isolated environment, then run:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pytest -q --tb=short --basetemp=.tools/pytest-recheck
.\.venv\Scripts\python.exe run.py --sim-only --check
cd frontend
npm ci
npm test
npx playwright install chromium firefox
npm run test:e2e
```

On Linux use `.venv/bin/python`; CI supplies `E2E_PYTHON=python`. `playwright install --with-deps chromium firefox` installs Linux system dependencies. E2E reserves port 8011 and creates disposable databases under ignored `output/e2e/`. It must not attach to an existing live server.

```powershell
cd ..
.\.venv\Scripts\python.exe evaluate.py --mode rule_based --steps 96 --seeds 42,101,2024 --output docs/validation/evaluation_report.md
.\.venv\Scripts\python.exe benchmark.py --days 7 --output docs/validation/seasonal_benchmark.json
.\.venv\Scripts\python.exe benchmark.py --days 1 --seasons winter --seeds 42 --modes fixed,scheduled,rule_based,forecast,llm --output docs/validation/llm_comparison.json
.\.venv\Scripts\python.exe tools/energyplus_smoke.py --engine PATH_TO_ENERGYPLUS --weather PATH_TO_EPW --output docs/validation/energyplus_smoke.json
```

The benchmark commands run from the repository root and replace their named evidence outputs. The evidence SHA-256 manifest uses paths relative to that root; normalize CRLF to LF in text files before verification. API tokens and real local databases are deliberately excluded from Git.

## Git history organization

Published history is retained for traceability. The unpublished changes and corrections are grouped into focused conventional commits, followed by this audit/evidence commit. See [the history tree](commit_history.md). No force push or fabricated author/date history is required. Each release is verified against the actual remote branch hash and GitHub Actions result rather than inferred from a local commit.
