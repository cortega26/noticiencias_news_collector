# Local Development Runbook

Status: Active  
Authority: Subordinate to `docs/SOURCE_OF_TRUTH.md`  
Scope: First-time setup and daily development for the full Noticiencias system

This document is the single starting point for getting the complete product running
locally — back-end pipeline, Refinery UI, and front-end site. It assumes the two
sibling repositories are checked out under the same parent directory:

```
noticiencias/
├── noticiencias/                  ← front-end (Astro)
└── noticiencias_news_collector/   ← back-end (Python)
```

---

## Prerequisites

| Requirement | Minimum version | How to verify |
|-------------|-----------------|---------------|
| Python | 3.13 | `python3 --version` |
| Node.js | 24.x | `node --version` — run `nvm use` in the front-end repo to apply `.nvmrc` |
| npm | bundled with Node.js | `npm --version` |
| make | any | `make --version` |
| git | any | `git --version` |
| Ollama (optional) | latest | `ollama --version` — only needed for LLM-enriched workflows |

> Note: CI and local development both use Node 24. Run `nvm use` in the front-end repo to apply the version from `.nvmrc`.

---

## Step 1: Bootstrap the back-end

```bash
cd noticiencias_news_collector
make bootstrap          # creates .venv with hash-pinned deps (idempotent)
cp .env.example .env    # copy the template; edit as needed (see below)
make config-validate    # confirm config.toml is valid
make migrate            # apply DB schema to SQLite (runs automatically in make refinery)
make test               # confirm the baseline test suite passes
```

### Required `.env` edits for local use

All variables in `.env.example` have safe defaults for local SQLite-based development.
The only supported local environment override file is the repo-root `.env`.
Do not create or edit `apps/refinery/.env`; Refinery no longer reads it.

The only values you may need to set for full pipeline functionality:

| Variable | Purpose | Required for |
|----------|---------|--------------|
| `NOTICIENCIAS__OLLAMA__API_URL` | Ollama endpoint | LLM enrichment, headline generation |
| `NOTICIENCIAS__OLLAMA__MODEL` | Model name | LLM enrichment |
| `NOTICIENCIAS__GEMINI__API_KEY` | Gemini key | Gemini-backed enrichment (optional path) |

Without Ollama or Gemini configured the collector still runs in dry-run and structural
test modes.

Note: a successful `GET /api/tags` response is not sufficient to prove local Ollama is
usable. The startup preflight now probes actual generation for each configured model, so
the machine must have enough free RAM to admit those models, not just list them.

---

## Step 2: Bootstrap the front-end

```bash
cd noticiencias
cp .env.example .env    # all vars are optional for local dev without R2
npm ci                  # use npm, not pnpm — matches CI (see CONTRIBUTING.md)
npm run validate:content
npm run build
npm run test:audit
```

The front-end `.env` variables are all optional in local development. Without
Cloudflare R2 credentials the site falls back to Astro's built-in image optimization.

---

## Step 3: Run the collector (dry run)

```bash
cd noticiencias_news_collector
python scripts/run_collector.py --dry-run
```

Dry-run mode fetches and normalizes articles but does not write to the database,
generate LLM enrichments, or produce any output files. Use it to verify connectivity
and source configuration without side effects.

---

## Step 4: Launch the Refinery UI

```bash
cd noticiencias_news_collector
make refinery           # starts Streamlit at http://localhost:8501
```

`make refinery` runs `make bootstrap-refinery` and `make migrate` automatically, then
launches `apps/refinery/admin_panel.py` in its isolated `.venv-refinery` environment.
Refinery resolves configuration from the same `config.toml` and repo-root `.env`
that `load_config()` uses everywhere else in the backend.

---

## Step 5: Run the front-end dev server

```bash
cd noticiencias
npm run dev             # starts Astro at http://localhost:4321
```

---

## Collector entrypoint reference

Three collector entrypoints exist. Use the table below to pick the right one:

| Command | Behaviour | When to use |
|---------|-----------|-------------|
| `python scripts/run_collector.py --dry-run` | Fetch + normalize; no DB writes, no LLM | Local testing, CI smoke check |
| `python scripts/run_collector.py` | Full single collection cycle with DB writes | One-shot runs, cron |
| `python scripts/run_collector.py --fast` | Full cycle, skip AI scoring | Quick data ingestion |
| `python scripts/run_collector.py --sources nature mit_news` | Single-source targeted run | Debugging a specific source |
| `python scripts/run_collector_continuous.py` | Infinite loop, respawns collector subprocess | Long-running daemon, Docker |
| `main.py` | Legacy compatibility surface | **Do not use for new work** — prefer the script above |

---

## Validation commands by change type

| Change type | Commands to run |
|-------------|-----------------|
| Back-end code only | `make lint && make type && make test` |
| Contract or adapter | `make lint && make type && make test && make test-contracts` |
| Orchestration, workflow, storage | `make lint && make type && make test && make test-boundaries` |
| Publication / Refinery | `make lint && make type && make test && make quality-gate` |
| Front-end content only | `npm run lint && npm run validate:content` |
| Front-end component or layout | `npm run lint && npm run validate:content && npm run build && npm run test:dist && npm run test:audit` |
| Cross-repo schema change | All of the above, both repos |

See `docs/AGENTS.md §10` (back-end) and `AGENTS.md §9` (front-end) for the full
change matrices.

---

## Common failure modes

| Error | Likely cause | Fix |
|-------|-------------|-----|
| `sqlite3.OperationalError: database is locked` | Parallel collector processes | `pkill -f run_collector.py` then retry |
| `429 Too Many Requests` | Aggressive rate limit config | Adjust `[rate_limiting]` in `config.toml`; see `docs/faq.md` |
| `500` from Ollama with `requires more system memory` | Host RAM/swap exhausted; model cannot be admitted | Free memory first (`ps aux --sort=-%mem | head`, stop stale `vitest`/Node jobs), then retry. If the machine still cannot fit the configured model, use Gemini or override to a smaller local Ollama model. |
| `Configuration validation failed` | Invalid `config.toml` value | Run `make config-validate` for details |
| `ModuleNotFoundError` | Stale or missing venv | `make bootstrap` |
| Front-end `astro check` fails | Schema mismatch in content file | `npm run validate:content` for field-level detail |
| Refinery UI blank after launch | Missing DB migration | `make migrate` |

For operational incidents see `docs/runbook.md` and `docs/collector_runbook.md`.  
For configuration questions see `docs/faq.md` and `docs/config_fields.md`.

---

## Docker (optional)

The `docker-compose.yml` provides a PostgreSQL-backed stack for production-parity
local testing. It is **not** the recommended path for day-to-day development.

```bash
cd noticiencias_news_collector
cp .env.example .env
# Set POSTGRES_PASSWORD in .env

docker compose --profile app up --build
```

Services:
- `db` — PostgreSQL 15
- `refinery` — Streamlit Refinery UI at `http://localhost:8501`
- `collector` — runs `--help` by default to prevent accidental scraping

To run a single collection cycle inside the container:

```bash
docker compose run --rm collector python scripts/run_collector.py --dry-run
```
