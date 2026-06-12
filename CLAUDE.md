# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Full governance doc:** [`docs/AGENTS.md`](docs/AGENTS.md) — read it before making any change.

**Mandatory workflow: Section 0.1 in AGENTS.md** — before every task, create/update `spec.md`, `todo.md`, and `tests/`; then work spec-first, check off todo, run tests after every meaningful commit, and call a review sub-agent every ~20 iterations. Consult `spec.md` before every change.

---

## Quick Commands

```bash
make bootstrap        # first-time setup (venv + hash-pinned deps)
make test             # fast unit suite (excludes slow tests/e2e_pipeline)
make test-all         # full suite incl. e2e   |  make test-e2e for e2e only
.venv/bin/pytest tests/path/to/test.py::test_name  # single test (make test takes no args)
make lint             # ruff + black + isort (check only)
make lint-fix         # auto-format + ruff fix
make type             # mypy strict on targeted files
make quality          # lint + type + bandit + pip-audit + semgrep
make quality-gate     # snapshot-based publication quality gate
make prepush          # test-all + quality-gate (pre-push gate)
make config-validate  # validate config.toml
make config-docs-check # ensure config docs are up to date
make test-contracts   # D1 contract enforcement tests
make test-boundaries  # D1 system boundary tests
make refinery         # launch Streamlit editorial UI
```

**Preferred collector entrypoint:** `python scripts/run_collector.py --dry-run`

## Project Map

```
noticiencias_news_collector/
├── news_collector/
│   ├── contracts/       # Pydantic boundary models + adapters (typed shapes)
│   ├── system/          # orchestration, bootstrap, observability
│   ├── collectors/      # RSS, HTML, Reddit, headless feed ingestion
│   ├── enrichment/      # NLP, LLM-based summary/translation strategies
│   ├── infrastructure/  # HTTP clients, LLM providers (Ollama, Gemini, NVIDIA), proxy
│   ├── storage/         # SQLAlchemy ORM, Alembic migrations, persistence
│   ├── scoring/         # relevance/quality/cognitive/heuristic/pre-scorers
│   ├── validation/      # quality gate rules
│   ├── taxonomy/        # category/tag normalization
│   ├── editorial/       # classification, policy, council, AI editor
│   ├── reranker/        # final ranking before export
│   ├── logic/workflows/ # refinery engine, PR orchestration, publication, image briefs
│   ├── serving/         # FastAPI read layer
│   ├── monitoring/      # health checks, detection, canary, reporting
│   ├── components/      # editorial (AI editor) + publishing (GitHub publisher)
│   └── utils/           # narrow helpers only (no mixed concerns)
├── apps/refinery/       # Streamlit editorial admin panel
├── scripts/             # CLI entrypoints (run_collector.py, quality_gate.py, etc.)
├── tests/               # contract, unit, integration, e2e, regression, security
├── docs/                # ADRs, runbooks, audits, architecture docs
├── config.toml          # primary runtime config
└── Makefile             # all validation commands
```

## Architecture Rules

- **Contracts** (`contracts/`) define typed cross-boundary shapes — no raw `dict[str, Any]` across packages.
- **Adapters** (`contracts/adapters.py`) are the only shape-conversion choke point.
- **I/O stays at edges** — collectors, enrichment, infrastructure, and serving own network/DB; policy modules (scoring, validation, taxonomy, editorial) must be runnable without network or DB.
- **Orchestration** (`system/`, `logic/workflows/`) coordinates but does not author rules.
- **Publication identity** must be deterministic and idempotent — no runtime time/randomness in slugs, filenames, or canonical URLs.
- **Tests are architectural evidence** — add/update when touching contracts, identity, batch logic, or package boundaries.

## Cross-Repo Contract

Backend ↔ frontend alignment depends on two files staying in sync:

| Backend | Frontend |
|---------|----------|
| `contracts/frontend_schema.py` (`AstroPost`) | `../noticiencias/src/content/config.ts` (Zod) |

Field parity enforced by `tests/test_contracts_sync.py::test_frontend_schema_field_parity`.
Both repos live under `../noticiencias/` sibling directory.

## Change Validation Matrix

| Change type | Risk | Minimum validation |
|---|---|---|
| Pure rule change (scoring/validation/editorial/taxonomy) | Medium | `make lint && make type && make test` |
| Contract/adapter/boundary | High | Baseline + `make test-contracts` |
| Orchestration/workflow/collector/storage/serving | High | Baseline + `make test-boundaries` |
| Publication identity / config schema / security | Critical | Baseline + targeted gates + `make quality` |

## Prohibited Patterns

- `except Exception: pass` — never
- New `manager`, `service`, or `factory` without clear lifecycle responsibility
- Business logic in `system/` just because "it's already coordinating things"
- Dict payloads across package boundaries (use contracts)
- Network/DB I/O inside `scoring/`, `validation/`, `taxonomy/`, or `editorial/`
- `asyncio.run()` below CLI/sync compatibility boundaries
