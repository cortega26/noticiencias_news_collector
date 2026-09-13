# Editorial modes

Status: Active. Configuration is the repository-root `config.toml`, resolved
by `noticiencias/config_manager.py`. `news_collector/editorial/policy.py`
owns mode thresholds; `news_collector/logic/workflows/refinery_engine.py`
owns how those settings affect publication.

```toml
[app]
editorial_mode = "standard"
```

| Mode | Critic threshold (0–100) | Auditor threshold (0–10) | Caveats required by policy |
| --- | --- | --- | --- |
| velocity | 70.0 | 3.0 | No |
| standard | 80.0 | 8.0 | Yes |
| strict | 85.0 | 8.5 | Yes |

`strict` also sets `require_no_hallucinations`. A policy flag records intent;
inspect its consumer before claiming it adds an independent enforcement stage.
The policy factory defaults unknown modes to standard; configuration validation
may reject a value before that factory is reached.

## Auditor behavior

`[editorial_auditor].blocking = false` makes cached auditor scores advisory,
including in standard/strict mode. Selecting a stricter editorial mode alone
does not turn the auditor into a publication gate.

When blocking is explicitly enabled and a cached score exists, the enforcement
path checks the epistemic threshold and required caveats. A missing cached
score currently proceeds; do not claim strict mode requires a fresh audit.
The optional auditor task runs after PR creation and stores metadata. These
semantics are separate from the pre-PR critic and fact-check stages.

Change settings through the supported config path and restart consumers that
load them at startup. Review the affected policy/workflow tests when changing
thresholds or enforcement, rather than changing docs to imply a stronger gate.
See [editorial_quality_system.md](editorial_quality_system.md) and
[PIPELINE_CONTRACTS.md](PIPELINE_CONTRACTS.md).
