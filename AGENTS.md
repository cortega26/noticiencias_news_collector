# AGENTS.md — Noticiencias Backend (News Collector)

> **Full governance document:** [`docs/AGENTS.md`](docs/AGENTS.md)
>
> This file is the canonical entry point for AI agents and contributors discovering the
> repository root. Read it first, then follow the link above for the complete rules.

---

## Quick Reference

### Before making any change

1. Read [`docs/AGENTS.md`](docs/AGENTS.md) in full.
2. Follow the **mandatory spec-driven workflow** (`docs/AGENTS.md §0.1`): create `spec.md` + `todo.md` + tests before starting, keep them updated, and run the tests after every meaningful commit.
3. Inspect the package boundaries touched by the change.
4. Classify the change using the **Change Matrix** in `docs/AGENTS.md §10`.
5. Run the required validation commands for that class.

### Baseline validation commands

```bash
make lint       # black --check + ruff (incl. isort rules) + Makefile-tab + Streamlit-deprecation checks
make type       # mypy (incremental: 3 files only) + pytest coverage run + coverage ratchet gate
make test       # unit suite (excludes slow tests/e2e_pipeline; use make test-all for the full suite)
```

> `make type` is not a strict-mypy gate. It type-checks a small target list
> (`scripts/generate_api_docs.py`, `utils/logger.py`, `utils/url_canonicalizer.py`),
> then runs pytest with coverage and fails if changed files drop below the
> coverage ratchet baseline (computed against `origin/main`).

Additional gates by change type:

| Change type | Extra commands |
|---|---|
| Contract or adapter | `make test-contracts` |
| Orchestration, workflow, storage, serving | `make test-boundaries` |
| Publication identity or Refinery publishing | `make quality-gate` |
| Config schema or doc generation | `make config-docs-check` |
| Dependencies, security, CI | `make quality` |
| Before pushing | `make prepush` (`test-all` + `quality-gate`) |
| Canonical CI gate (plan 041) | `make verify-ci` |

### Safe entry points

| Task | Command |
|---|---|
| First-time setup | `make bootstrap` (Python 3.13; hash-pinned installs from `requirements.lock`) |
| Validate config | `make config-validate` |
| Run collector (no side effects) | `python scripts/run_collector.py --dry-run` |
| Launch Refinery admin (current, Astro) | `make admin` (runs the serving API `:8000` + GUI `:4321` together, one Ctrl+C stops both; login gate skipped in dev). Split form: `make serve` + `make admin-dev`. |
| Launch Refinery admin (legacy, Streamlit) | `make refinery` (isolated `.venv-refinery`; runs migrations first) |
| Run full quality gate | `make quality` |

Notes:

- `make quality-gate` is snapshot-first and needs no LLM; `make quality-gate-refresh` regenerates snapshots using a local LLM (overwrites committed snapshots — use deliberately).
- Refinery (Streamlit) has its own venv (`bootstrap-refinery`); test it with `make test-refinery`.
- `apps/admin/` (Astro, `make admin-install` once, then `make admin` to run the full stack; also `admin-dev`/`admin-build`/`admin-test`, and `make serve` for the API alone) reached feature parity with the Streamlit panel and is the app to use going forward. The Streamlit panel (`apps/refinery/`) is being kept as a fallback until the Astro app is confirmed flawless in daily use — don't remove it without asking.

### Key files

| File | Purpose |
|---|---|
| `docs/AGENTS.md` | Full engineering governance law |
| `docs/RUNBOOK_LOCAL_DEV.md` | Step-by-step bootstrap for both repos |
| `docs/PRODUCT_FLOW.md` | RSS-to-live-page product flow |
| `docs/PIPELINE_CONTRACTS.md` | Cross-repo contract shapes and failure semantics |
| `docs/ARCHITECTURE.md` | Package map, dependency direction, extension rules |
| `docs/ci.md` | What CI workflows/gates actually run |
| `docs/SOURCE_OF_TRUTH.md` | Which files win when docs and code disagree |
| `docs/INDEX.md` | Full docs directory index |
| `news_collector/contracts/frontend_schema.py` | Cross-repo publication contract mirror |
| `config.toml` | Primary runtime configuration |
| `.env.example` | Environment variable template |

### Project map

```
noticiencias_news_collector/
├── news_collector/
│   ├── contracts/       # Pydantic boundary models + adapters
│   ├── system/          # orchestration, bootstrap, observability
│   ├── collectors/      # RSS, HTML, Reddit, headless feed ingestion
│   ├── enrichment/      # NLP, LLM-based summary/translation strategies
│   ├── infrastructure/  # HTTP clients, LLM providers, proxy
│   ├── storage/         # SQLAlchemy ORM, Alembic migrations, persistence
│   ├── scoring/         # relevance/quality/cognitive/heuristic/pre-scorers
│   ├── validation/      # quality gate rules
│   ├── taxonomy/        # category/tag normalization
│   ├── editorial/       # classification, policy, council, AI editor
│   ├── reranker/        # final ranking before export
│   ├── logic/workflows/ # refinery engine, PR orchestration, publication
│   ├── serving/         # FastAPI read layer
│   ├── monitoring/      # health checks, detection, canary, reporting
│   ├── components/      # editorial (AI editor) + publishing (GitHub publisher)
│   └── utils/           # narrow helpers only (no mixed concerns)
├── apps/admin/          # Astro editorial admin panel (current — use this)
├── apps/refinery/       # Streamlit editorial admin panel (legacy fallback, kept until apps/admin/ is confirmed flawless)
├── scripts/             # CLI entrypoints
├── tests/               # contract, unit, integration, e2e, regression, security
├── docs/                # ADRs, runbooks, audits, architecture docs
├── config.toml          # primary runtime config
└── Makefile             # all validation commands
```

### Architecture rules

- **Contracts** (`contracts/`) define typed cross-boundary shapes — no raw `dict[str, Any]` across packages.
- **Adapters** (`contracts/adapters.py`) are the only shape-conversion choke point.
- **I/O stays at edges** — collectors, enrichment, infrastructure, and serving own network/DB; policy modules (scoring, validation, taxonomy, editorial) must be runnable without network or DB.
- **Orchestration** (`system/`, `logic/workflows/`) coordinates but does not author rules.
- **Publication identity** must be deterministic and idempotent — no runtime time/randomness in slugs, filenames, or canonical URLs.
- **Tests are architectural evidence** — add/update when touching contracts, identity, batch logic, or package boundaries.

### Change validation matrix

| Change type | Risk | Minimum validation |
|---|---|---|
| Pure rule change (scoring/validation/editorial/taxonomy) | Medium | `make lint && make type && make test` |
| Contract/adapter/boundary | High | Baseline + `make test-contracts` |
| Orchestration/workflow/collector/storage/serving | High | Baseline + `make test-boundaries` |
| Publication identity / config schema / security | Critical | Baseline + targeted gates + `make quality` |

### Forbidden assumptions

- `main.py` has been removed. Use `python scripts/run_collector.py`.
- Do not write to the front-end repo directly — publication goes through PRs only.
- Do not add dict payloads across package boundaries without a typed contract.
- Do not add I/O inside rule modules (`scoring/`, `validation/`, `taxonomy/`, `editorial/`).
- Do not use `except Exception: pass` anywhere.

### Cross-repo contract

The back-end publication contract mirrors the front-end schema:

| Back-end (source of mirror) | Front-end (render authority) |
|---|---|
| `news_collector/contracts/frontend_schema.py` | `../noticiencias/src/content.config.ts` |

Any change to either file is a **critical** cross-repo contract change. Run both repos'
full validation suites and update `docs/PIPELINE_CONTRACTS.md`.
