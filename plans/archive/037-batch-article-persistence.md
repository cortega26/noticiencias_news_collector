# Plan 037: Make bulk article persistence truly set-based

> **Executor instructions**: Preserve canonicalization, exact/content/near-duplicate semantics, atomic rollback, and in-batch clustering while reducing query count. Measure before and after. Update plan 037 in `plans/README.md` when complete.
>
> **Drift check (run first)**: `git diff --stat e43bd30..HEAD -- news_collector/storage/article_repository.py news_collector/storage/database.py news_collector/storage/models.py tests/integration/test_database.py tests/unit/test_database_race_conditions.py tests/test_database_simhash_behavior.py`

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: HIGH
- **Depends on**: plans/033-make-config-refresh-live.md, plans/034-centralize-article-admission.md
- **Category**: perf
- **Planned at**: backend `e43bd30`, 2026-07-21

## Why this matters

`save_articles_bulk()` is bulk in transaction shape only: each item performs separate URL, content-hash, and near-duplicate candidate queries. A 100-item collection batch can issue hundreds of reads before inserts. Set-based prefetch plus in-memory batch decisions can preserve behavior while making database work scale with chunks, not articles.

## Current state

- `news_collector/storage/article_repository.py:526-685` loops over inputs inside one session.
- Lines 568-590 perform one URL query and one content-hash query per item.
- Lines 593-601 call `_assign_cluster()` per item; `_assign_cluster()` at lines 946-1024 may issue up to three prefix queries plus a fallback query.
- `articles_exist()` at lines 156-179 already demonstrates chunked `IN` lookup for SQLite parameter limits.
- `news_collector/storage/models.py:72-83,243-249` has unique URL/content-hash protection and simhash lookup fields.
- Atomic collision expectations exist in `tests/unit/test_database_race_conditions.py:126-188`; basic bulk retry behavior exists in `tests/integration/test_database.py:62-98`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Storage tests | `.venv/bin/python -m pytest tests/integration/test_database.py tests/unit/test_database_race_conditions.py tests/test_database_simhash_behavior.py -q` | all pass |
| Query benchmark | `.venv/bin/python scripts/benchmark_bulk_persistence.py --articles 100 --max-selects 12` | 100 unique items persist and SELECT count stays within documented bound |
| Full checks | `make lint && make typecheck && make test` | exit 0 |

## Scope

**In scope**: bulk input normalization, in-batch URL/hash dedupe, chunked existing-key lookups, batched near-duplicate candidate prefetch, in-memory cluster assignment for staged rows, bulk query instrumentation/benchmark, and repository tests.

**Out of scope**: single-article save behavior, changing dedupe thresholds/algorithms, weakening atomic rollback, schema/index changes, or accepting invalid articles (plan 034 owns admission).

## Git workflow

- Branch: `advisor/037-set-based-article-save`.
- Commit example: `perf(storage): batch article dedupe and clustering reads`.

## Steps

### Step 1: Freeze behavior with a query-count fixture

Add fixtures containing valid rows, duplicate canonical URLs, same-content/different-URL rows, existing database duplicates, near duplicates, unrelated rows, equal timestamps, invalid payloads, and a forced unique race. Instrument SQLAlchemy `before_cursor_execute` in tests to classify SELECT/INSERT statements without timing assertions.

**Verify**: behavior fixtures pass on current code and a 100-row baseline records the current SELECT count.

### Step 2: Normalize and deduplicate the input once

Convert/validate every item, apply plan 034's admission boundary, canonicalize URL/date, normalize text, and compute hash/simhash/prefix exactly once into a private prepared-row structure. Deduplicate by canonical URL and content hash in stable input order. Retain safe reason counters for skipped invalid/duplicate rows.

**Verify**: unit tests prove canonicalization/hash/simhash helpers are called once per valid input and first-in-batch wins consistently.

### Step 3: Prefetch exact duplicates in sets

Query all existing canonical URLs and non-null content hashes in bounded `IN` chunks using one session, respecting SQLite parameter limits. Filter prepared rows against those sets before constructing ORM objects. Rely on database unique constraints as the final concurrency guard.

**Verify**: exact-dedupe SELECT count is bounded by the number of parameter chunks, not input length; retry persists zero rows.

### Step 4: Prefetch and assign near-duplicate clusters in memory

Load existing candidate columns once per distinct relevant prefix group (with a documented bounded fallback), then apply the existing hamming/time/confidence algorithm in memory. As each new row is accepted, add it to the candidate map so later rows in the same input batch can join its cluster exactly as sequential insertion would. Preserve deterministic input order.

**Verify**: existing single-save and new batch fixtures produce equivalent cluster membership/confidence, including two near duplicates introduced in the same batch.

### Step 5: Preserve atomic flush and prove the bound

Construct ORM rows, flush at the configured batch size, and commit once. Preserve full rollback on any non-filtered integrity error. Add the deterministic benchmark and report prepared/skipped/saved counts plus statement totals.

**Verify**: benchmark exits 0 with at most the documented SELECT bound; forced unique collision leaves no partial batch rows.

## Test plan

- Behavior parity for URL, content hash, simhash cluster, invalid input, status override, and retry.
- In-batch versus pre-existing duplicates and near duplicates.
- SQL statement counts for 1, 50, 100, and >SQLite-parameter-limit inputs.
- Atomic rollback under race/non-unique integrity failures.

## Done criteria

- [ ] Exact duplicate queries scale by chunks, not articles.
- [ ] Near-duplicate candidate reads scale by distinct prefix groups, not articles.
- [ ] Single/bulk dedupe and clustering outcomes remain equivalent.
- [ ] Atomic collision behavior remains covered.
- [ ] Benchmark and full backend checks pass.

## STOP conditions

- Stop if plan 034's admission boundary is not available; do not duplicate normalization/admission again.
- Stop if batched candidate prefetch changes cluster outcomes in characterization tests; report the exact fixture before changing semantics.
- Stop if query reduction requires removing a database uniqueness guard.

## Maintenance notes

Keep query-count tests based on statement classes, not elapsed time. Revisit chunk bounds for each supported database driver.
