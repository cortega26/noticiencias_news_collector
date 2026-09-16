# Plan 092: Batch the per-candidate URL existence check in RSS extraction

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat e77a039..HEAD -- news_collector/collectors/rss_collector.py tests/unit/collectors/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M (raised from S on 2026-09-16: first attempt STOPped correctly — the coverage ratchet demands ≥90% whole-file line coverage for changed files and `rss_collector.py` sits at ~76% pre-existing; closing the ~54-line gap needs honest characterization tests, see Step 3b)
- **Risk**: LOW
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `e77a039`, 2026-09-16; refreshed 2026-09-16 after the first executor run

## Why this matters

The RSS candidate loop issues one `SELECT … WHERE url=?` per feed item — up to
`4 × max_articles_per_source` round-trips per source per cycle — an N+1 on the
hottest collector loop, scaling SQLite lock contention linearly with feed size.
A bulk `articles_exist()` API already exists and is already used for the same
purpose in `base_collector.py`. After this plan, each source pays one batched
existence query instead of up to hundreds.

## Current state

The relevant files, each with one line on its role:

- `news_collector/collectors/rss_collector.py` — candidate filtering loop (lines 776-802)
- `news_collector/storage/article_repository.py` — `articles_exist(urls)` bulk check (lines 256-279)
- `news_collector/collectors/base_collector.py` — house-pattern caller of the bulk API (~lines 995-1000)
- `tests/unit/collectors/test_rss_collector.py` — collector tests incl. a `parsed_ok == 3` regression test (extend)

Excerpts of the code as it exists today:

`news_collector/collectors/rss_collector.py:776-802`:

```python
max_articles = cfg.collection_config["max_articles_per_source"]
candidate_multiplier = 4
fetch_limit = max_articles * candidate_multiplier

count = 0
for cand in candidates:
    if count >= fetch_limit:
        break
    ...
    # Duplicate filter
    if self.db_manager.article_exists(cand["url"]):
        continue

    filtered_candidates.append(cand)
    count += 1
```

`news_collector/storage/article_repository.py:256-279` — the bulk API (chunked `IN` queries, canonicalizes URLs internally):

```python
def articles_exist(self, urls: List[str]) -> Set[str]:
    """Batch check for existing articles by URL. ..."""
    if not urls:
        return set()
    urls = [canonicalize_url(u) or u for u in urls]
    CHUNK_SIZE = 500
    ...
```

`news_collector/collectors/base_collector.py:995-1000` (approx) — the exemplar:

```python
if valid_candidates:
    candidate_urls = [str(a.url) for a in valid_candidates]
    existing_urls = self.db_manager.articles_exist(candidate_urls)
```

Repo conventions that apply here:

- LAW-B10: collector loops are performance-sensitive; no N+1 inside them.
- `self.db_manager` exposes both `article_exists` and `articles_exist` (confirm the manager forwards the bulk method — check `storage/database.py:352` area; if the manager lacks the forwarder, add that one-line delegation rather than working around it).

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Install   | `make bootstrap`         | declared   | exit 0 |
| Lint      | `make lint`              | declared   | exit 0 |
| Type      | `make type`              | declared   | exit 0, ratchet passes |
| Tests     | `make test`              | declared   | all pass |
| Boundaries| `make test-boundaries`   | declared   | all pass |

## Scope

**In scope** (the only files you should modify):

- `news_collector/collectors/rss_collector.py` (candidate loop only)
- `news_collector/storage/database.py` (only if the one-line `articles_exist` forwarder is missing)
- `tests/unit/collectors/test_rss_collector.py` (new tests only)

**Out of scope** (do NOT touch, even though they look related):

- The date filter, `fetch_limit` accounting, pre-scorer, or `_process_article` BEHAVIOR — characterization tests may pin behavior, never change it.
- Double Pydantic validation per article (`rss_collector.py:1143` + `base_collector.py:941`) — real but separate; do not bundle.
- Other collectors' loops (Reddit/HTML/headless) — same pattern may exist; report, don't expand.
- Production code beyond the Step-2 batching change — the coverage backfill (Step 3b) is TESTS ONLY. If reaching 90% requires touching production code (refactors for testability), STOP and report instead.

## Git workflow

- Branch: `advisor/092-batch-existence-check`
- Conventional commits, e.g. `perf(collectors): batch RSS duplicate existence checks`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `Install`, then `Lint`, `Type`, `Tests` on the unmodified checkout. On any
`declared`-command failure on the clean tree: **STOP and report** with exact output.

**Verify**: all commands match their expected results on the unmodified checkout.

### Step 1: Confirm the bulk path covers this call site's semantics

1. Read `article_exists` (singular) and confirm whether it canonicalizes its input; compare with `articles_exist` (plural), which canonicalizes (`article_repository.py:266`). If singular does NOT canonicalize and plural does, the bulk version is strictly more correct — note this in the commit message.
2. Confirm `self.db_manager` in `rss_collector.py` forwards `articles_exist` (check `storage/database.py` ~line 352). If missing, add the one-line forwarder mirroring the singular one.
3. Note the `cand["url"]` access: keep it as-is (a missing `url` key raising `KeyError` here is pre-existing behavior; do not change error semantics in a perf plan).

**Verify**: you can state the canonicalization parity in one sentence; `make lint` → exit 0 if you touched `database.py`.

### Step 2: Hoist the check out of the loop

Restructure `rss_collector.py:780-802` to:

1. Before the loop, collect candidate URLs in order: `urls = [cand["url"] for cand in candidates]` (same key access as today).
2. Single call: `existing = self.db_manager.articles_exist(urls)` (returns a set of existing URLs — canonicalized; membership-test each candidate's URL the same way the set was built, i.e. compare `cand["url"]` against the set, and if canonicalization could mismatch, canonicalize the candidate side identically — read the bulk implementation once more and mirror it exactly).
3. In the loop, replace `if self.db_manager.article_exists(cand["url"]): continue` with the set-membership check. Keep the date filter, `fetch_limit`/`count` accounting, and append order exactly as today.

**Verify**: `make lint` → exit 0; `.venv/bin/python -m pytest tests/unit/collectors/test_rss_collector.py -q` → pass.

### Step 3: Add a batching regression test

In `tests/unit/collectors/test_rss_collector.py`, with a fake `db_manager` exposing both methods (singular raising `AssertionError` if called, bulk returning a fixed set):

1. Feed N candidates with K known-existing → assert singular was never called, bulk called once, and the filtered list excludes exactly the K.
2. Assert output order and `fetch_limit` truncation match the old behavior (e.g. more candidates than `fetch_limit` with duplicates interspersed).

**Verify**: new tests pass; full collector test dir green.

### Step 3b: Backfill characterization coverage on `rss_collector.py` (added in refresh)

The ratchet (`scripts/coverage_ratcheter.sh`) demands ≥90% whole-file line
coverage for every changed module. `rss_collector.py` sits at ~76% for
pre-existing reasons, so the Step-2 change cannot land without lifting the
file to 90% with honest tests. Prior executor's per-function miss inventory
(2026-09-16, RE-VERIFY with the coverage report — line numbers shift):

- `collect_from_source` ~31 missed lines
- `_fetch_feed_robust` ~27 missed lines
- `_process_article` ~17 missed lines
- `_extract_articles_from_feed` ~9 missed lines
- `get_session_stats` ~5 missed lines, misc ~5

Rules for the backfill (all must hold, else STOP and report):

1. TESTS ONLY — no production-code change beyond Step 2 (not even "trivial" refactors for testability).
2. Characterization style: fake transports/DB/clocks, assert CURRENT behavior (fetch/retry branches, error paths, session stats). If current behavior looks buggy, pin it and REPORT it — do not fix it here.
3. No real network, no real timers (use the repo's fake-clock/fake-sleep patterns, e.g. `test_rate_limit_and_backoff.py`).
4. No brittle time/date-sensitive assertions; no tests that depend on pytest execution order.

**Verify**: coverage report shows `news_collector/collectors/rss_collector.py` ≥90% line coverage; `make type` (mypy + ratchet) → exit 0.

### Step 4: Run the full gates

**Verify**: `make lint && make type && make test && make test-boundaries` → all exit 0.

## Test plan

- New fake-DB tests pinning single-call batching + identical filtering/truncation semantics.
- New characterization tests lifting `rss_collector.py` to ≥90% line coverage (Step 3b).
- Existing RSS collector tests (incl. the `parsed_ok` health regression) stay green.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `make lint`, `make type`, `make test`, `make test-boundaries` all exit 0 — with `make type`'s ratchet explicitly green on `rss_collector.py` (≥90%)
- [ ] `grep -n "article_exists(" news_collector/collectors/rss_collector.py` → no matches (only the bulk call remains)
- [ ] New batching + backfill tests exist and pass
- [ ] No production-code change beyond the Step-2 batching edit
- [ ] `git diff --name-only e77a039...HEAD` lists only the in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- Canonicalization differs between singular/bulk in a way that changes *which* articles count as duplicates (measure with a test; if bulk is stricter/looser, report instead of silently changing dedup semantics).
- `self.db_manager` is a different type than the one exposing `articles_exist` (check the constructor first).
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

- If other collectors show the same per-item pattern, they are separate small plans — same recipe, one file each.
- Reviewers: the behavioral risk is entirely in URL normalization parity; the test in Step 3 is the load-bearing artifact.
- **Deferred:** per-article double Pydantic validation on the ingest hot path — unblocked, adjacent, needs a validated-model pass-through design.
