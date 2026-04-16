# AGENTS.md — Noticiencias Backend (News Collector)

> **Full governance document:** [`docs/AGENTS.md`](docs/AGENTS.md)
>
> This file is the canonical entry point for AI agents and contributors discovering the
> repository root. Read it first, then follow the link above for the complete rules.

---

## Quick Reference

### Before making any change

1. Read [`docs/AGENTS.md`](docs/AGENTS.md) in full.
2. Inspect the package boundaries touched by the change.
3. Classify the change using the **Change Matrix** in `docs/AGENTS.md §10`.
4. Run the required validation commands for that class.

### Baseline validation commands

```bash
make lint       # Ruff + Black + isort
make type       # mypy strict
make test       # full unit test suite
```

Additional gates by change type:

| Change type | Extra commands |
|---|---|
| Contract or adapter | `make test-contracts` |
| Orchestration, workflow, storage, serving | `make test-boundaries` |
| Publication identity or Refinery publishing | `make quality-gate` |
| Config schema or doc generation | `make config-docs-check` |
| Dependencies, security, CI | `make quality` |
| Before pushing | `make prepush` |

### Safe entry points

| Task | Command |
|---|---|
| First-time setup | `make bootstrap` |
| Validate config | `make config-validate` |
| Run collector (no side effects) | `python scripts/run_collector.py --dry-run` |
| Launch Refinery UI | `make refinery` |
| Run full quality gate | `make quality` |

### Key files

| File | Purpose |
|---|---|
| `docs/AGENTS.md` | Full engineering governance law |
| `docs/RUNBOOK_LOCAL_DEV.md` | Step-by-step bootstrap for both repos |
| `docs/PRODUCT_FLOW.md` | RSS-to-live-page product flow |
| `docs/PIPELINE_CONTRACTS.md` | Cross-repo contract shapes and failure semantics |
| `docs/ARCHITECTURE.md` | Package map, dependency direction, extension rules |
| `docs/SOURCE_OF_TRUTH.md` | Which files win when docs and code disagree |
| `docs/INDEX.md` | Full docs directory index |
| `news_collector/contracts/frontend_schema.py` | Cross-repo publication contract mirror |
| `config.toml` | Primary runtime configuration |
| `.env.example` | Environment variable template |

### Forbidden assumptions

- Do not use `main.py` — it is deprecated; use `python scripts/run_collector.py`.
- Do not write to the front-end repo directly — publication goes through PRs only.
- Do not add dict payloads across package boundaries without a typed contract.
- Do not add I/O inside rule modules (`scoring/`, `validation/`, `taxonomy/`, `editorial/`).
- Do not use `except Exception: pass` anywhere.

### Cross-repo contract

The back-end publication contract mirrors the front-end schema:

| Back-end (source of mirror) | Front-end (render authority) |
|---|---|
| `news_collector/contracts/frontend_schema.py` | `../noticiencias/src/content/config.ts` |

Any change to either file is a **critical** cross-repo contract change. Run both repos'
full validation suites and update `docs/PIPELINE_CONTRACTS.md`.
