# Plan 107: Analytics baseline + cost/SLO dashboard

> **Executor instructions**: Measure first. No product behavior changes — instrumentation and reporting only. Update the `107` row in `plans/README.md` when complete.
>
> **Drift check (run first)**:
> `git diff --stat HEAD -- src/config.yaml src/components/template/common/Analytics.astro news_collector/monitoring/ news_collector/perf/ 2>/dev/null; git status --short | head`

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: None (Wave 0 — runs first, parallel-safe with 108)
- **Category**: observability
- **Planned at**: backend `9fa77b6`, 2026-09-16

## Why this matters

Frontend analytics is wired but dead (`src/config.yaml` `analytics.id: null` → `Analytics.astro` renders nothing), and per-article LLM cost is unknown (headline critic = up to 6 calls/article, fact-check = 1 call/claim, auditor = +20% publishes). Every later plan (108–114) needs these numbers to prove impact. Instrumentation with zero behavior change is the cheapest unblock available.

## Current state (verified)

- FE `src/config.yaml:71-74`: `analytics.vendors.googleAnalytics.id: null`; `src/components/template/common/Analytics.astro:1-32` no-ops; CSP in `CommonMeta.astro:11` already allows gtag hosts.
- BE costs: `config.toml [ollama]/[gemini]/[nvidia]`, `max_headline_retries=2` (`ai_editor.py:479-491,1372-1417`, Stage-5 uncached), fact-check per-claim calls (`ai_editor.py:2290-2515`), auditor `sampling_rate=0.2, blocking=false` (`config.toml:530-536`).
- Throughput ceiling: `config.toml [collection]` 12h cadence, `max_concurrent_requests=1`, `max_concurrent_sources=10`, `max_articles_per_source=5`.

## Scope

**In scope**: privacy-friendly analytics enablement (Plausible, NOT GA4 — avoids consent-banner scope); `$published_article` cost report (LLM calls x model, headline retries, fact-check claims, auditor runs); SLO snapshot (ingest success %, dead-source %, PR validation pass %, `make perf` baseline into `reports/perf/`).

**Out of scope**: GA4, consent banner, any collector/scoring/publish behavior change, alerting/paging.

## Steps

### Step 1: Enable Plausible analytics (frontend)
Set the analytics ID in `src/config.yaml`, confirm `Analytics.astro` emits on build, confirm `test:dist` + `check:search-budget` still pass and LCP/CLS do not regress. No other template changes.

**Verify**: production-preview page source contains the analytics script; `npm run build`, `npm run test:dist`, `npm run check:search-budget` green.

### Step 2: Per-article cost report (backend, edge-only per LAW-B4)
New `scripts/ops/cost_report.py` (plus narrow unit tests) aggregating from existing logs/metadata: model calls per publish (drafter/critic/headlines/fact-check/auditor), headline-retry count, publish lead time (collect → PR → live). Read-only over logs/DB; no pipeline changes.

**Verify**: `pytest` new tests pass; report emits valid JSON on a seeded sample; `make lint` clean.

### Step 3: SLO snapshot
Record one baseline row: ingest success %, source-failure %, PR pass %, `make perf` output reference. Store under `reports/` (gitignored-friendly; do not commit large artifacts — commit only the summary if repo convention allows, else keep local and paste numbers into the plan's closing note).

**Verify**: numbers captured; `make perf` exit 0 or clean-skip with `reports/perf/SKIPPED` per `docs/ci.md`.

## Verification (full gate)

| Purpose | Command | Expected |
|---|---|---|
| Ledger | `.venv/bin/python scripts/validate_plans_ledger.py` | OK |
| Backend gates | `make lint && make type && make test` | exit 0 |
| Perf baseline | `make perf` | exit 0 or clean SKIPPED |
| Frontend | `npm run build && npm run test:dist && npm run check:search-budget` (in `../noticiencias`) | exit 0 |

## STOP conditions

- STOP if baseline `make lint/type/test` is red on the clean tree — record, do not fix-forward outside scope.
- STOP if analytics vendor requires a consent banner or leaks PII — fall back to a different privacy-first vendor, do not ship GA4 silently.

## Git workflow

- Branch: `advisor/107-analytics-cost-slo`.
- Commit example: `chore: enable privacy analytics and cost baseline`.
