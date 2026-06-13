# Plan 015: Spike — surface per-source enrichment economics in the Refinery Analytics tab

> **Executor instructions**: This is a **design/spike plan**. The deliverable is an
> investigation note + a thin, **read-only** UI slice — NOT a full feature. Do not
> change the enrichment pipeline or the metrics schema. Honor STOP conditions.
> Update this plan's row in `plans/README.md` when done.
>
> **Drift check (run first)**: `git diff --stat b30248f..HEAD -- scripts/generate_autonomous_report.py news_collector/observability/enrichment_metrics_store.py apps/refinery/admin_panel.py`

## Status

- **Priority**: P3
- **Effort**: M (spike-scoped)
- **Risk**: LOW (additive, read-only)
- **Depends on**: none
- **Category**: direction
- **Planned at**: commit `b30248f`, 2026-06-12

## Why this matters

The pipeline already records per-source enrichment economics — how often a source yields publishable content and how expensive it is to fetch (headless browser, proxy). `scripts/generate_autonomous_report.py` turns that into a Markdown report nobody reads in-flow. The Refinery's Analytics tab shows only collection *volume*. Surfacing yield/cost per source tells editors which sources are worth the fetch spend and which to blacklist — a decision they currently make blind (and which ties to plan 016).

## Grounding evidence

- `scripts/generate_autonomous_report.py:7,16-50` — reads `enrichment_metrics.db`
  (`METRICS_DB_PATH`, default `data/metrics/production/enrichment_metrics.db`), table
  `enrichment_metrics`, and computes per-source `yield_pct = total_publishable/total_enrichment_attempted`,
  `headless_rate = headless_success/headless_attempts`, `proxy_rate = proxy_success/proxy_attempts`.
- `news_collector/observability/enrichment_metrics_store.py` — the **store class** for
  that DB. Prefer reading through this (or the `Source`/metrics ORM) over raw `sqlite3`.
- `apps/refinery/admin_panel.py:2412-2491` — the Analytics tab ("Analítica del Sistema"),
  which currently shows article counts / score distribution / top sources by avg score,
  with **no** enrichment metrics (`grep "enrichment_metrics" apps/refinery/admin_panel.py` → none).

## Spike deliverables

1. **Investigation note** at `docs/spikes/enrichment-economics-dashboard.md` answering the open questions.
2. **A thin read-only UI slice**: one expander/section in the Analytics tab showing a
   per-source table of `yield_pct`, `headless_rate`, `proxy_rate` (and attempt counts),
   sourced via `enrichment_metrics_store.py`. No writes, no new metric collection.
3. A **recommendation**: is the fuller dashboard (cost rollups, failure heatmap, links to
   the Sources tab) worth building, and the smallest next step.

## Open questions the note must answer

- **Where is the metrics DB in the editor's environment?** `METRICS_DB_PATH` defaults to
  `data/metrics/production/...`. Is it present/populated where the Refinery runs, or only
  in the autonomous production job? If absent locally, the slice must degrade gracefully
  ("no enrichment metrics available") — confirm by reading how `generate_autonomous_report.py`
  and `enrichment_metrics_store.py` open it.
- **What does `enrichment_metrics_store.py` expose?** Read it; reuse its read API rather
  than re-implementing the `sqlite3` + `yield_pct` math from the script. If it lacks a
  read-all method, note what minimal read method would be needed (don't add write paths).
- **Is the per-source key the same `source_id`** used elsewhere in the UI (so a future
  step can link a row to the Sources tab)? Confirm.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| AST parse | `.venv/bin/python -c "import ast; ast.parse(open('apps/refinery/admin_panel.py').read()); print('ok')"` | `ok` |
| Lint | `make lint` | exit 0 |
| Refinery tests | `.venv/bin/pytest tests/decompose_refinery -q` | pass |

## Scope

**In scope:** `docs/spikes/enrichment-economics-dashboard.md` (create); a read-only section in `apps/refinery/admin_panel.py`'s Analytics tab; a read-only helper if `enrichment_metrics_store.py` lacks one (no writes).

**Out of scope:** the enrichment pipeline, metric collection, the metrics schema, `strategy_locks.yaml`, any write/mutation, the frontend repo.

## Git workflow

- Branch: `advisor/015-enrichment-economics-spike`; commits: note, then UI slice. Do NOT push.

## Steps

### Step 1: Investigate + write the note
Read `enrichment_metrics_store.py` and `generate_autonomous_report.py:16-50`; answer the open questions with `file:line` evidence; end with a recommendation and the proposed fuller-dashboard shape.

### Step 2: Thin read-only slice
Add a section/expander in the Analytics tab that loads per-source metrics via the store and renders a sorted table (yield desc). Guard for the metrics DB being absent (show an info message, never crash).

**Verify:** AST parse + `make lint` clean; the tab renders without the metrics DB (degrades gracefully) — exercise this in a quick `.venv/bin/python` import smoke if a full Streamlit run isn't feasible, and note it.

## Done criteria

- [ ] `docs/spikes/enrichment-economics-dashboard.md` answers all open questions with evidence + a recommendation
- [ ] A read-only per-source enrichment table appears in the Analytics tab, sourced via `enrichment_metrics_store.py`, degrading gracefully when the DB is absent
- [ ] No writes/mutations; no pipeline/schema change (`git status` shows only in-scope files)
- [ ] AST parse + `make lint` + `make test` green
- [ ] `plans/README.md` row updated

## STOP conditions

- The metrics DB is not reachable from the Refinery environment at all → deliver the note + recommendation explaining the gap; do not fabricate data or wire new collection.
- Reading the metrics cleanly requires more than a small read method on the existing store → report; don't reshape the store.

## Maintenance notes

- Keep it read-only; the cost/ROI numbers are advisory. The natural follow-up is linking each row to the Sources tab + blacklist action (plan 016).
