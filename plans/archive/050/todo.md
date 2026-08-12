# Plan 050 TODO

## Pre-work (done earlier in session)
- [x] e2e audit of live export `data/exports/latest_articles.json`:
      34/50 rows >30 days, oldest 1705 days; freezing confirmed
      (`rescore_days_back=14`, `final_score` persisted on write).
- [x] Proved weight change alone is insufficient: recency contributes
      only 0.1*(recency_comp); old high-quality articles still rank above.
- [x] Confirmed `_calculate_recency_score` floors at 0.05 and its
      `>168h` tail never reaches 0.
- [x] Confirmed `get_articles_by_score` has no age filter (only
      `final_score >= min` + `published_at IS NULL`).
- [x] Created plan file `plans/050-candidate-max-age-gate.md` and this spec.

## Implement
- [x] Add `candidate_max_age_days` to `ScoringConfig` (`noticiencias/config_schema.py`).
- [x] Add `candidate_max_age_days = 30` under `[scoring]` in `config.toml`.
- [x] Rework `_calculate_recency_score` tail: reaches 0.0 at exactly
      `candidate_max_age_days*24` hours; remove 0.05 floor.
- [x] Add `max_age_days` filter to `get_articles_by_score`
      (`article_repository.py` + `database.py` wrapper) using
      `coalesce(published_date, collected_date)`.
- [x] Thread `candidate_max_age_days` into `export_latest_articles`,
      `get_top_articles`, `_execute_final_selection`, and the
      non-dry-run export in `scripts/run_collector.py`.
- [x] Update `_FakeSelectionDatabase.get_articles_by_score` in
      `tests/unit/test_system_dry_run_collection.py` to accept `max_age_days`.

## Tests
- [x] `test_basic_scorer.py`: reduce to `0.0` at/after 30 days, `~0.00`
      at 29d23h59m, monotone, no floor.
- [x] New `tests/integration/test_database.py::test_get_articles_by_score_honors_age_gate`:
      age-gate exclusion for old articles, keeps fresh ones.
- [x] Existing `test_recency_decay` still green.
- [x] `tests/e2e_pipeline/test_pipeline_e2e.py`: fixtures had hardcoded
      2026-05-07 dates that aged past the 30-day gate; added
      `_relative_fixture_dates` so replay `published` timestamps are shifted
      to ~2h before now (relative gaps preserved). All 13 e2e scenarios green.

## Verify (docs/AGENTS.md §10 — config schema change = Critical-ish; run baseline + relevant gates)
- [x] `make lint`
- [x] `make type`
- [x] `make test`
- [x] `make test-contracts` — 47 passed; coverage gate 77.56% vs 80% is a
      pre-existing failure unrelated to this change (no files under
      `news_collector/contracts` were touched).
- [x] `make test-boundaries` (storage/query + orchestration touched) — 3 passed.
- [x] `make config-docs-check` (docs/config_fields.md regenerated with the new field)
- [x] Regenerate export in a scratch path with `max_age_days=30`; assert
      0 rows older than 30 days (e2e smoke of the reported symptom).
- [x] `git diff --stat` limited to intended files.

## Follow-up (not part of this fix, recorded for later)
- [ ] `latest_articles.json` committed export currently holds 34/50 rows
      >30 days; regenerating it is a separate artifact update, and reverting
      it removed a committed secret — do not couple to this fix.
