# Plan 050: Enforce a 30-day candidate recency gate

> **Executor instructions**: This is a correctness fix derived from a live
> e2e audit of the scoring/export pipeline. Articles older than ~30 days
> keep occupying most slots of the curation panel's top-50 because (a)
> `final_score` freezes at scoring time and the rescore window is only 14
> days, and (b) the candidate query has no age cutoff. The user's decision:
> an article older than 30 days must not be a candidate at all, and the
> recency score must reach 0.00 just before the cutoff instead of flooring
> at 0.05.
>
> Drift check: `git status --short` and `git diff --stat HEAD` must show
> only plan files + the intended code/test/config changes.
>
> Must finish with `make lint && make type && make test .venv-refinery
> test-refinery`-style validation per `docs/AGENTS.md` §10.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: MEDIUM (scoring/config schema)
- **Depends on**: none (standalone correctness fix)
- **Category**: bugfix
- **Planned at**: backend `10dd7e8`, 2026-08-06

## Why this matters

The curation panel (`apps/refinery/admin_panel.py`) and the final selection
both consume `get_articles_by_score`, which orders ALL completed,
unpublished articles by persisted `final_score DESC` with **no upper bound
on age**. Because scoring only re-runs for articles collected within
`rescore_days_back = 14` days and recency is blended into the persisted
score at write time, articles from months ago retain a high frozen score
and crowd out fresh ones. The recency curve also clamps to a 0.05 floor,
so the "recency" signal never reaches zero and the user's attempts to fix
ranking via the `recency` weight had no visible effect.

## Current state

- `news_collector/scoring/basic_scorer.py:282_ — `_calculate_recency_score`
  decays but `return max(0.05, …)` floors the score at 5% forever.
- `news_collector/storage/article_repository.py:1057` —
  `get_articles_by_score` has no age parameter/filter.
- `news_collector/scoring/coordinator.py:95-97` — `rescore_days_back=14`.
- `config.toml` `[scoring.weights]` — `recency = 0.1` (user tried `0.3`,
  no visible effect because scores are frozen).
- `plans` numbering ends at 049.

## Scope

**In scope**: a configurable candidate age cutoff (`candidate_max_age_days
= 30`), applied by every path that feeds a candidate list or the panel
(export, final selection, top articles), plus a recency decay that reaches
0.00 at day ~30 (no 0.05 floor) and hard-excludes at `candidate_max_age_days`.

**Out of scope**: changing `[scoring.weights]`, changing `rescore_days_back`,
changing the CognitiveScorer relevance blend, or resurrecting publication
state logic.

## Design

1. `candidate_max_age_days: PositiveInt = Field(default=30)` on
   `ScoringConfig` (`noticiencias/config_schema.py:445`) and
   `candidate_max_age_days = 30` in `config.toml` `[scoring]`.
2. `_calculate_recency_score`: replace the tail with a monotonic decay
   that reaches `0.0` exactly at `candidate_max_age_days * 24` hours and
   is `0.0` beyond it; remove the `0.05` floor. Reference age keeps the
   existing `published_date` (or `collected_date` penalty) rule.
3. `get_articles_by_score(..., max_age_days: Optional[int] = None)`:
   when set, exclude rows where `coalesce(published_date, collected_date)
   < now - max_age_days`. Same reference rule as the recency function.
4. Thread `max_age_days` from runtime config into the callers that build
   candidate or panel lists:
   - `news_collector/system/reporting.py` — `export_latest_articles`,
     `get_top_articles`.
   - `news_collector/system/__init__.py` — `_execute_final_selection`.
   - `scripts/run_collector.py` — non-dry-run export branch.
5. Leave the dry-run and DB-fallback panel paths and `get_articles_by_category`
   (already bounded by `days_back=7`) untouched except for test fakes.

## Verification

- New unit test: recency == `0.0` at/after `candidate_max_age_days`,
  ~0.00 at `29d23h59m`, monotone decreasing, no 0.05 floor.
- New repository test: `get_articles_by_score(max_age_days=N)` excludes
  an article whose `coalesce(date) < cutoff` and keeps a fresh one.
- Existing `test_recency_decay` keeps passing.
- e2e smoke: regenerate `data/exports/latest_articles.json` via the
  repository query with `max_age_days=30` and assert zero rows older than
  30 days (mirrors the failing reality observed in audit: 34/50 rows >30d).
- `make lint && make type && make test` (and, because it is a config
  schema change, `make config-docs-check` if present).