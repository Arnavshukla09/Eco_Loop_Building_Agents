# Project correction plan

> **Historical correction record (25 November 2026).** The completion notes and availability statements below reflect that validation session. Later work supersedes the EnergyPlus/browser availability limits and the fan-advisory description for the Python simulator. See the [upgrade execution record](upgrade_plan.md) and [26 November 2026 audit](project_audit_2026-11-26.md) for current verification.

Created 2026-11-25 after source review and reproduction of the reported issues.

## Scope

1. Match active/reference simulation seeds on startup and reset. Carry measured
   baseline power through telemetry, history, persistence, and the energy chart.
2. Validate all actuation paths, calculate slew limits inside the simulation lock,
   report actual per-zone values, and preserve failed actuator results.
3. Start and stop EnergyPlus explicitly, validate API handles, and reject stale
   agent decisions when a reset occurs during inference.
4. Scope recovered history to the active run; isolate tests from the user's database
   and Ollama service; verify exact configured model tags and MCP credentials.
5. Make MCP benchmark success depend on tool results, fix automatic evaluation mode,
   persist container data, and describe fan recommendations as advisory.
6. Add regression coverage, run the complete backend suite and frontend checks, and
   record verification and remaining integration limits here.

Existing README edits and docs/assets are user changes and will be preserved.

## Completed changes

- Active and reference simulations use the same configurable seed at startup and
  reset. A failed reference is marked unmeasured instead of being reused out of sync.
- Baseline power is measured per step, persisted in a nullable database column,
  streamed to the browser, and plotted directly. Existing databases receive an
  additive migration; older readings retain gaps for missing baseline power.
- REST and MCP return requested and acknowledged values separately, including
  per-zone results and partial failures. Slew limiting happens under the step lock.
  Autonomous audit records store the values actually accepted after limiting.
- Nonfinite setpoints and simulation speeds are rejected. All decision providers
  pass through canonical actuation validation, with controller-level fallback if
  a provider raises. Model health requires the configured model tag.
- Resets invalidate decisions still awaiting inference, count and persist their
  initial step, clear old reference/decision state, and flush pending database work.
  Shutdown also flushes pending writes.
- History recovery filters by active run, merges chronologically, prefers memory
  over stale database duplicates, and normalizes timestamp timezone representation.
- MCP query credentials require exact parameter matching. Authenticated HTTP
  requests authorize tool calls without duplicating credentials in tool arguments.
  This is verified with an actual MCP initialize/tools-call exchange through ASGI.
- EnergyPlus initialization/shutdown are called by the controller. The adapter
  uses positional IDF arguments, zone names matching the reference file, separate
  sensor/actuator/meter handles, accumulated energy, timestep pacing, and explicit
  failure for missing handles, completed simulations, and stale observations.
- Fan recommendations are labelled advisory. Repeated WebSocket broadcasts
  replace an existing timestep instead of adding duplicate history points.
- MCP benchmarks initialize a live environment, execute mutations, and inspect
  returned error/success payloads. Automatic mode selection, malformed-response
  setup, benchmark attribution, and output paths were corrected. Machine-specific
  exports outside the project were removed.
- Docker Compose persists the database in a named volume and probes Ollama with
  its own CLI. The FastMCP requirement now matches the API version used in code.
- Tests use temporary databases and mocked Ollama startup checks; the corrupted
  JSON and authentication matrix tests no longer depend on local services or order.
  Frontend regression tests run in CI.

## Validation

- `py -m pytest -q --tb=short -p no:cacheprovider`: **81 passed** on Python
  3.14.3, with two dependency deprecation warnings. Includes full FastAPI lifespan
  startup/shutdown, WebSocket coverage, and a real MCP HTTP protocol exchange.
- `npm test` in `frontend`: **5 passed** (measured baseline including zero/missing
  data, repeated timestep handling, history cap, and actual setpoint feedback).
- `npm run build` in `frontend`: **passed**.
- Full evaluation: three seeds, 96 steps per scenario, **45.62% mean rule-based
  savings**, **63.9% mean comfort adherence**. All 10 MCP tools succeeded across
  50 repetitions each. Fresh evidence is in [validation/evaluation_report.md](validation/evaluation_report.md)
  and [validation/evaluation_results.json](validation/evaluation_results.json).
- `git diff --check` passes for task changes. Pre-existing README whitespace and
  content edits were preserved.

## Remaining integration limits

- EnergyPlus is not installed here. Lifecycle, handle validation, stale-step
  rejection, meter accumulation, and time conversion are covered by mocks, but
  the real engine has not been run. The bundled IDF is a reference scaffold with
  only Core HVAC/thermostat definitions and no complete envelope. A complete
  five-zone IDF and EPW weather file are required for a real-engine demonstration.
  Missing required handles now produce an explicit error.
- Docker is unavailable here, so Compose changes were inspected but containers
  were not built or launched.
- Ollama was offline during the fresh evaluation. The saved validation report
  measures deterministic rule-based control; it makes no claim of LLM advantage.
- No browser automation runtime is installed. Frontend behavior is checked with
  Node regression tests plus the Vite production build; visual browser QA remains.
- The thermal model and fan behavior remain research approximations, and the
  24-hour benchmark does not establish annual or physical-building performance.
