# Plan 045: Measure and optimize the ranked article API query

> **Executor instructions**: This is evidence-gated performance work. Establish deterministic baselines and query plans before changing SQL or indexes; keep API output and cursor semantics identical. Update plan 045 in `plans/README.md` when complete.
>
> **Drift check (run first)**:
> `git diff --stat e43bd30..HEAD -- news_collector/serving/api.py news_collector/storage/models.py news_collector/storage/article_repository.py alembic tests/test_serving_api.py tests/perf scripts docs/operations.md`

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MEDIUM
- **Depends on**: plans/029-fix-backend-coverage-ratchet.md
- **Category**: performance
- **Confidence**: MEDIUM; the query shape is structurally expensive, but production cardinality and database plans were not available in the workspace.
- **Planned at**: backend `e43bd30`, 2026-07-21

## Why this matters

`GET /v1/articles` is the read path for ranked content, yet it materializes full `Article` and latest `ScoreLog` ORM rows, computes the latest log with a grouped subquery, and filters topics through JSON extraction/string search. Existing tests prove correctness on three SQLite rows but provide no statement, plan, payload, or latency budget. Measurement-first optimization can reduce database and serialization cost without guessing at a schema change.

## Current state

- `news_collector/serving/api.py:325-424` selects `(Article, score_log_alias)`, outer-joins a grouped `max(calculated_at)` subquery, applies keyset pagination, and fetches `page_size + 1` complete ORM entities.
- `_build_article_payload` at `api.py:235-251` uses a narrow subset of those columns plus the latest log's `score_explanation`.
- `_apply_topic_filters` at `api.py:222-232` uses SQLite-specific `json_extract` plus `instr` once per topic, with AND semantics and no relational topic index.
- `Article.__table_args__` has category/status/score/date and status/date/source indexes, but not a proven index matching the unfiltered score/date/id cursor order. `ScoreLog` has `(article_id, calculated_at)`.
- `tests/test_serving_api.py:13-222` covers filtering, cursor stability, health, and related articles on three records; there is no ranked-query performance suite or production-scale fixture.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Correctness | `.venv/bin/python -m pytest tests/test_serving_api.py -q` | response/filter/cursor contract passes |
| Deterministic benchmark | `.venv/bin/python scripts/benchmark_serving_api.py --articles 10000 --score-logs-per-article 3 --samples 30 --output reports/perf/serving_api.json` | emits dataset seed, query count, p50/p95, payload bytes, and plan fingerprints |
| Performance gate | `.venv/bin/python -m pytest tests/perf/test_serving_api_perf.py -q` | budgets derived from accepted baseline pass without network access |
| Full backend gates | `make lint && make typecheck && make test && make test-contracts` | exit 0 |

## Scope

**In scope**: deterministic SQLite baseline, PostgreSQL profile when the supported test service is available, SQL statement counts, `EXPLAIN` capture, selected-column/projection changes, latest-score-log query shape, cursor/filter equivalence, and an index only when plans demonstrate it and plan 046's migration path is proven.

**Out of scope**: speculative topic-schema normalization, changing API fields or topic AND semantics, offset pagination, caching stale responses, production load testing without authorization, or adding an index based only on intuition.

## Git workflow

- Branch: `advisor/045-ranked-query-profile`.
- Commit example: `perf: profile and tighten ranked article query`.
- Land benchmark fixtures/baseline separately from the measured optimization.

## Steps

### Step 1: Freeze the response and cursor contract

Expand serving tests for equal scores/dates, null scores, multiple score logs with tied timestamps, multiple sources/topics, date boundaries, maximum page size, malformed cursors, and traversal across all pages without gaps/duplicates. Snapshot normalized response keys and ordering rather than generated timestamps.

**Verify**: the suite fails if `Article.id` is removed from the final ordering, latest-log selection changes, or topic filters switch from AND to OR.

### Step 2: Add a deterministic query benchmark

Create a seeded generator with configurable article/log/topic distributions and no external calls. Measure warm/cold p50/p95, SQL statement count, selected row/column volume, response bytes, and `EXPLAIN QUERY PLAN` for unfiltered, source, date, one-topic, multi-topic, first-page, and deep-cursor cases. Add an opt-in PostgreSQL mode using the same seed and `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` with redacted output.

**Verify**: two runs produce the same result ordering, query count, dataset checksum, and explain fingerprint; timing variance is reported rather than hidden.

### Step 3: Set budgets from evidence

Record the planned-at baseline in `reports/perf/serving_api.json` and document hardware/database profile. Define a generous deterministic CI regression ratio plus absolute statement/payload budgets; do not make shared-runner microseconds the sole gate. Identify the dominant cost separately for no-topic and topic queries.

**Verify**: an intentional extra query and full-content payload selection fail stable non-timing budgets.

### Step 4: Optimize the measured dominant path

First replace full ORM hydration with an explicit selected-column result that contains exactly the response/cursor inputs. Then evaluate latest-log alternatives supported by both databases (window/subquery/correlated query) against the benchmark. If topic JSON scans dominate, document the cardinality and create a separately reviewed normalization/index migration rather than embedding an unproven schema redesign here.

**Verify**: all contract fixtures are byte-equivalent after normalized timestamps, SQL statements do not increase, and accepted p95/row-volume budgets improve on both supported database profiles.

### Step 5: Add an index only with plan proof and migration safety

If `EXPLAIN` shows a repeatable sort/scan bottleneck, specify the exact predicate/order/index, write the Alembic migration after plan 046 is complete, test empty/upgrade/downgrade paths, and compare write/storage cost. Remove redundant indexes only with usage/equivalence evidence.

**Verify**: both SQLite and PostgreSQL planners use or intentionally reject the index as documented; migration tests and insert/write profiles stay within an accepted budget.

## Test plan

- Expanded functional/API cursor and filtering matrix.
- Seeded 10k-record benchmark with 1/3/many score logs and realistic topic selectivity.
- SQLite always; PostgreSQL in supported integration CI.
- Query-count, projection-volume, response-equivalence, and migration/index tests.

## Done criteria

- [ ] Ranked-query behavior and ordering are explicitly regression-tested.
- [ ] Reproducible baseline and accepted budgets exist for representative cases.
- [ ] Any query/index change is tied to an observed plan/cost and improves the target without regression.
- [ ] API response, topic semantics, and keyset pagination remain compatible.
- [ ] Benchmark and backend verification pass in canonical CI.

## STOP conditions

- Stop optimization if representative production cardinality/selectivity cannot be approximated; deliver the measurement harness and request sanitized statistics.
- Stop an index change until plan 046 proves migration/deployment ordering.
- Stop if SQLite and PostgreSQL require incompatible SQL; preserve a shared semantic implementation or explicitly isolate/test dialect-specific paths.

## Maintenance notes

Store baselines with dataset and environment metadata. Re-profile after schema, ranking, topic, or response-field changes instead of carrying stale timing numbers forward.
