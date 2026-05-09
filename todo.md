# Todo: Cross-Repo Pipeline Hardening, Source Reliability, and LatAm Relevance

Consult `spec.md` before every change.

## Phase 0 — Baseline and scope

- [x] Read `AGENTS.md` and `docs/AGENTS.md`
- [x] Inspect publication, source-health, enrichment-router, and scoring boundaries
- [x] Replace `spec.md` with the cross-repo hardening initiative
- [x] Replace this `todo.md` with the new phased checklist
- [x] Confirm baseline targeted tests before code changes
  - `pytest tests/test_source_health_schema.py tests/unit/test_diagnostics.py tests/unit/enrichment/test_router.py tests/unit/test_strategy_optimizer.py -q`

## Phase 1 — Cross-repo publication validation

- [x] Add a typed publication validation summary contract
- [x] Add a backend-owned frontend validation runner that executes:
  - `npm ci`
  - `npm run lint`
  - `npm run validate:content`
  - `npm run build`
  - `npm run test:dist`
  - `npm run test:audit`
- [x] Persist a machine-readable validation summary artifact for each smoke attempt
- [x] Upgrade `.github/workflows/publication-smoke.yml` to use the full validation runner
- [x] Add deterministic tests under `tests/e2e_cross_repo/` for success and failure-class coverage
- [x] Re-run the new publication smoke tests

## Phase 2 — Source health and Scrapling audit

- [x] Add a typed source-health contract with stable flat-record serialization
- [x] Unify `news_collector/system/reporting.py` and `news_collector/diagnostics.py` to emit the same shape
- [x] Add operational-state classification:
  - `healthy_full_text`
  - `healthy_summary_only`
  - `partial_yield_flaky`
  - `failing_suppressed_candidate`
- [x] Add failure taxonomy classification:
  - `feed_fetch_failure`
  - `article_fetch_blocked`
  - `content_too_short`
  - `js_render_required`
  - `anti_bot_block`
  - `extraction_parser_mismatch`
  - `editorial_relevance_rejection`
  - `publication_contract_failure`
  - `unknown_failure`
- [x] Include stable strategy/cost fields in `source_health.json`
- [x] Add source-strategy consistency helpers for contradictory `summary_only`/Scrapling usage
- [x] Add or update tests for source health schema, diagnostics, and router/strategy behavior
- [x] Re-run focused source-health and strategy suites

## Phase 3 — Deterministic relevance and golden coverage

- [x] Add a deterministic LatAm/public-interest relevance helper or regression surface
- [x] Add a replayable golden fixture set for ranking/regression behavior
- [x] Add tests proving:
  - LatAm-relevant stories outrank campus/admin filler
  - universal-interest science outranks low-value institutional updates
  - weak source expansion does not bias deterministic ranking
- [x] Re-run focused ranking/relevance tests

## Phase 4 — Validation and workflow hardening

- [x] Run targeted cross-repo, source-health, router, and relevance suites together
  - `pytest tests/e2e_cross_repo tests/test_source_health_schema.py tests/unit/test_diagnostics.py tests/unit/enrichment/test_router.py tests/unit/test_strategy_optimizer.py -q`
- [ ] Run required broader backend gates for this change class
  - `make lint`
  - `make type`
  - `make test-contracts`
  - `make test-boundaries`
  - `make quality-gate`
- [x] Record any pre-existing repo-wide blockers here if broader gates fail for unrelated reasons
  - `make lint` still fails on 39 pre-existing repo files outside this change set that Black would reformat.
  - `make type` still fails on pre-existing incompatibility in `news_collector/system/bootstrap.py:330` (`GeminiProvider` assigned where `NvidiaProvider` is inferred).
- [x] Ask a fresh sub-agent to review `spec.md` and the current implementation for gaps if this work reaches another large iteration block

## Phase 5 — Full pipeline E2E harness

- [x] Fix replay-driven candidate persistence drift so non-publishable articles are still saved deterministically
- [x] Add typed pipeline E2E contracts for run summaries and stage snapshots
- [x] Add a reproducible harness that runs:
  - replay fixture -> collector
  - temp DB persistence
  - validation + scoring + final selection
  - export + approval selection
  - `RefineryEngine`
  - frontend validation runner
  - diagnostics bundle persistence
- [x] Add a CLI entrypoint for scenario-based E2E runs
- [x] Add deterministic replay fixtures for:
  - `happy_path_latam_winner`
  - `blocked_source_fallback`
  - `low_value_beats_high_value_regression`
  - `frontend_rejects_generated_post`
  - `stuck_publishing_recovery`
  - `duplicate_permalink_collision`
- [x] Add a dedicated deterministic suite under `tests/e2e_pipeline/`
- [x] Add coverage proving every failing scenario records one root failure stage and a machine-readable bundle
- [x] Re-run the focused E2E suites after each meaningful edit batch

## Phase 6 — Live and workflow separation

- [x] Split deterministic PR-safe E2E from nightly/manual live-source coverage
- [x] Add a scheduled/manual workflow for live source drift checks using the critical cohort
- [x] Emit a differential live report for newly broken, strategy-mismatched, or non-publishable sources
