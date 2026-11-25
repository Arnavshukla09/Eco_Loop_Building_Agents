# Commit history and release organization

The published chronology is retained. The release adds focused conventional commits and documents historical evidence; it does not erase earlier engineering phases or rewrite published author/date information.

```text
main
├── af688aa  feat: initial hackathon submission
├── 6ec027b  chore: Office temporary-file ignores
├── 3cf3924  chore: MIT license
├── 89fa8c5  docs: project study guide
├── abf78b7  docs: evaluation harness and report
├── 56eab71  eval: real Ollama calls and corrected evidence
├── bc8f1db  eval: Qwen2.5 inference metrics
├── 45fc7ef  audit: technical review and telemetry resilience
├── 216f99a  fix: measured baseline, async LLM, tests and CI
├── 3bc0129  fix: authentication, validation and concurrency guards
├── 54bde15  feat: persistence and provider abstraction
├── cc4d6a8  refactor: live provider actuation and restart coverage
├── 9b08019  feat: sensor fault handling and slew limits
├── 5bb1171  feat: matched multi-seed evaluation
├── 20eedfe  fix: attribution, comfort and fallback verification
└── 2026-11-26 release
    ├── fix(core): secure control, persistence and truthful telemetry
    ├── feat(simulation): five-zone EnergyPlus and matched benchmarks
    ├── fix(dashboard): resilient measured telemetry and browser E2E
    ├── build(ci): locked validation and hardened deployment
    └── docs(audit): historical comparison and validation evidence
```

The release entries describe commit subjects; use `git log --graph --oneline --decorate --all` for exact assigned hashes. The release includes the pre-existing unpublished upgrade work plus audited corrections. A local ignored snapshot preserves the starting files.

Validation and unresolved external integration work are recorded in [the dated audit](project_audit_2026-11-26.md). GitHub source availability does not imply a running public application.
