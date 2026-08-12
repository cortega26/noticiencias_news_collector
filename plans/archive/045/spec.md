# Plan 045 working notes: Measure and optimize the ranked article API query

Authoritative spec: `plans/045-measure-and-optimize-ranked-api-query.md`.

## Status (2026-08-11): Steps 1-4 DONE; Step 5 index REJECTED by evidence

Step 1 (contract freeze) was already done (11 serving tests). This pass
delivered Steps 2-4 and evaluated Step 5 empirically — the proposed index
is **rejected by measurement**, not by opinion.

## Step 2: deterministic benchmark — DONE

`scripts/benchmark_serving_api.py`: seeded SQLite generator (10k/100k
articles, configurable logs-per-article, topic distribution replicating
the real corpus), measures p50/p95/min/max, SQL statement count (via
SQLAlchemy event hook), payload bytes, and EXPLAIN QUERY PLAN fingerprints
for unfiltered/source/date/one-topic/multi-topic/deep-cursor cases.
Same-seed runs reproduce ordering, statement counts, and plan
fingerprints; timing variance is reported, not hidden. Seeding uses
`bulk_save_objects` (100k rows in seconds).

Baseline captured in `reports/perf/serving_api.json` (10k articles, 3
logs each, seed 42): all cases ~19-32ms p50, exactly 1 statement per
request, ~12.8KB payloads.

## Step 3: budgets — DONE (non-timing by design)

`tests/perf/test_serving_api_perf.py` (7 tests, module-scoped 10k fixture):
- statement count per request <= 1 (catches N+1 / lost projection)
- payload <= 32KB (catches full-entity hydration regression)
- response contract stable (ordering, keys, cursor presence)

Per the plan's own instruction, shared-runner microseconds are NOT the
gate; structural budgets are.

## Step 4: explicit projection — DONE, measured

`news_collector/serving/api.py` ranked query now selects exactly the
columns the payload/cursor need (`with_entities`-style explicit
projection: 13 Article columns + score_log id/explanation) instead of
hydrating full Article + ScoreLog ORM entities (which pull `content`
Text and all JSON columns).

Measurement (same-process raw SQLite, 100k articles): projection is
neutral at the SQL level (SQLite fetches by rowid either way) but the
API-level A/B shows the real win in the ORM/serialization layer:
**p50 225.8ms -> 209.0ms** (100k, TestClient, warm). SQL statement count
unchanged at 1; response bytes unchanged (payload shape identical).

## Step 5: index — REJECTED by evidence

EXPLAIN at 10k showed the grouped `max(calculated_at)` subquery
(MATERIALIZE anon_1, scanning all score_logs every request) plus
`USE TEMP B-TREE FOR ORDER BY` — the plan's predicted bottleneck. Three
candidates were tested at 100k with a decisive same-process A/B:

| Index | p50 (100k) | Verdict |
|---|---|---|
| none (baseline) | 185-199ms | — |
| `(processing_status, final_score DESC, collected_date DESC, id DESC)` | 418-466ms | **2.3x SLOWER** |
| `(processing_status, collected_date, id)` ASC | ~201ms | neutral |
| window-function latest-log rewrite | 39-46ms @10k raw | slower than grouped subquery |

Root cause: the ORDER BY is `coalesce(final_score, ?)` — a function, so
no index can satisfy the sort (temp b-tree is unavoidable); the DESC
index forces random rowid lookups (final_score is uncorrelated with
rowid), destroying cache locality at scale. The 10k numbers that looked
promising (28ms -> 16ms) were an artifact of the whole table fitting in
cache. Per the plan's own STOP condition ("add an index only when plans
demonstrate it"), no index is added. The grouped subquery is retained
over the window-function alternative (measured slower).

## Final status

- Step 1: DONE (pre-existing, 11 tests).
- Step 2: DONE — benchmark + baseline report.
- Step 3: DONE — non-timing perf gate (7 tests).
- Step 4: DONE — explicit projection, measured p50 225.8 -> 209.0ms @100k.
- Step 5: evaluated; index REJECTED by evidence (2.3x regression at scale).

Plan archived as DONE with the index rejection documented — the durable
deliverables are the benchmark harness and the structural perf gate,
which now protect the ranked query against regressions without depending
on production cardinality.
