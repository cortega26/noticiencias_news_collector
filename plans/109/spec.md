# Plan 109: Batch publication (up to 5, per-item outcomes)

> **Executor instructions**: Extend the plan-106 `publication_pipeline.py` seam. Never widen `refinery_engine.py`. Identity must stay deterministic (LAW-B5). Update the `109` row in `plans/README.md` when complete.
>
> **Drift check (run first)**:
> `git diff --stat HEAD -- news_collector/logic/workflows/publication_pipeline.py news_collector/logic/workflows/publication_run_workflow.py news_collector/serving/api.py news_collector/contracts/admin.py apps/admin/`.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH (publication identity; keep the blast radius narrow)
- **Depends on**: 106 (done); Wave 1 — parallel-safe with 110 (disjoint files)
- **Category**: efficiency/throughput
- **Planned at**: backend `9fa77b6`, 2026-09-16

## Why this matters

Serving publishes exactly one article per run (`PublicationRunWorkflow.start(article_id XOR article_url)`, 409 single-flight, 3600s lease). Reaching 3x/week cadence through single-article PRs is the editorial bottleneck. `refinery_engine.process_articles(list)` already loops per-article with `publication_attempts/{id}.json` persistence — the serving path just never uses batch.

## Current state (verified)

- `logic/workflows/publication_run_workflow.py:93-267`: durable single-flight single-article, daemon thread + `_run()` → `run_publication_pipeline(process_id=...)`, success iff `status==success and processed_count>0`.
- `logic/workflows/publication_pipeline.py:456-755`: Refine-Only (`process_id!=None`, skips collector) vs Bulk (`None`); owns its own `DatabaseManager()`; LLM preflight fail-closed.
- `refinery_engine.py:224-300`: batch-capable loop, continues on per-article error.
- Admin contracts: `news_collector/contracts/admin.py` (`AdminPublishRequest/Started/Status`); GUI `apps/admin/src/pages/triage.astro + lib/api.ts`.

## Scope

**In scope**: `AdminPublishBatchRequest(ids[1..5])` + per-item result (`success/skip/fail` + reason, LAW-B6, no silent drops); idempotent re-run (same batch → same slugs, no new identities, LAW-B5); single-flight/lease reuse from 060-Phase 4a semantics (409/404 mapping); triage multi-select UI.

**Out of scope**: raising the batch cap above 5, scheduler/cron changes, touching `refinery_engine.py` orchestration, PR-batching into one PR (still one PR per article; batching is at dispatch, not git).

## Steps

### Step 1: Contract + pipeline batch entry
Add batch request/result shapes in `contracts/admin.py` (adapters stay the only mapping choke point, LAW-B2). Add a batch entry in `publication_pipeline.py` that iterates the existing single-article path and aggregates per-item outcomes; reuse `publication_attempts/{id}.json` persistence. No new abstraction layers (LAW-B9).

**Verify**: new contract unit tests (cap enforced, empty rejected, per-item aggregation incl. one-bad-item case); `make test-contracts`.

### Step 2: Serving thin wrapper
`serving/api.py` batch endpoint as thin HTTP wrapper dispatching to the pipeline (no editorial transitions or direct DB writes in the handler, per §3.6). Preserve 409/404/lease semantics.

**Verify**: boundary tests for 409 conflict, unknown-id 404, lease-recovery; `make test-boundaries`.

### Step 3: Admin GUI multi-select
Triage multi-select (≤5) + batch status view in `apps/admin` (`triage.astro`, `lib/api.ts`, `types.ts` mirrors). Handle 409 body and `cancelled/interrupted` statuses (060-4a precedent).

**Verify**: `npm run test` (vitest) + manual preview walkthrough; backend `make test` unaffected.

## Verification (full gate)

| Purpose | Command | Expected |
|---|---|---|
| Ledger | `.venv/bin/python scripts/validate_plans_ledger.py` | OK |
| Baseline | `make lint && make type && make test` | exit 0 |
| Contracts | `make test-contracts` | exit 0 |
| Boundaries | `make test-boundaries` | exit 0 |
| Publication | `make quality-gate` | exit 0, snapshots untouched (never `-refresh`) |

## STOP conditions

- STOP if any previously-successful publish changes identity (slug/filename/canonical) — the wave check from plan 106 applies.
- STOP if the handler needs direct DB writes or workflow logic duplication — split into pipeline + thin wrapper instead.
- STOP if baseline gates are red on the clean tree.

## Git workflow

- Branch: `advisor/109-batch-publication`.
- Commit example: `feat(workflows): batch publication dispatch with per-item outcomes`.
