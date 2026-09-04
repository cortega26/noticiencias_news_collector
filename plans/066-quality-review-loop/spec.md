# Plan 066 — Quality review loop (recent publication runs + scores)

## Goal

Editors can review what the pipeline actually published and how healthy
each article was: a new Curation Desk page (`/quality`) listing recent
publication runs with outcome (PR link / failure) and quality signals
(readability IFSZ + grade, stage checklist). This turns plans 063/065
from log lines into a reviewable surface, and produces the score
distribution needed before any blocking thresholds.

## Design

Backend (additive, typed contracts — no shape changes elsewhere):

1. `contracts/admin.py`: `AdminQualityReadability` (ifsz/ifh/grade/
   suitability/words/sentences, all Optional), `AdminQualityStageItem`
   (name/success/details), `AdminQualityRunItem` (run_id/status/
   started_at/finished_at/article_id/article_url/final_slug/
   output_filename/pr_url/failure_class/error/readability/stages),
   `AdminQualityAggregate` (count/succeeded/failed/with_readability/
   avg_suitability), `AdminQualityRecentEnvelope` (runs/aggregate/meta).
2. `serving/api.py`: `GET /v1/admin/quality/recent?limit=20 (1..50)` —
   `WorkflowRun` rows (`run_type='publication'`, newest first), summary
   from `run_metadata.summary`, readability extracted defensively from the
   first `readability` stage (older runs → null, never 500). Auth:
   `verify_admin_token` like every admin read.

Frontend (`apps/admin`, mirrors existing pages):

3. `types.ts` + `api.ts` (`getQualityRecent`).
4. `pages/quality.astro`: summary chips (runs / succeeded / avg
   suitability / with-readability) + table (run, when, article slug with
   `/article?id=` link when numeric, outcome PR-link-or-failure badge,
   readability badge IFSZ+grade or `—`) + expandable `<details>` stage
   checklist. All styling via global classes + Tailwind utilities (NOT
   scoped `<style>` for dynamic DOM — plan 061 lesson).
5. Nav entry in `AdminLayout.astro` after Analytics.

## Non-goals

- Critic-average persistence (log-only today) and auditor rollup — v1
  shows persisted signals; both are specced as follow-ups.
- Blocking thresholds on readability — needs this page's data first.
- Changing attempt-file format, run lifecycle, or any existing contract.

## Verification

- Serving test: 3 seeded runs (success+readability / failed+failure /
  legacy-no-summary) → shape, null-tolerance, newest-first, `limit` 422.
- `make lint && make type && make test && make test-contracts &&
  make test-boundaries`; `admin: check + test + build`; live snapshot of
  `/quality` against the dev stack (20 real attempt files exist).
