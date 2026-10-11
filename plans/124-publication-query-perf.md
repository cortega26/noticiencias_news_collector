# Plan 124: Fix publication query scans, nondeterministic ordering, and batch setup tax

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 04016ca..HEAD -- news_collector/storage/article_repository.py news_collector/logic/workflows/publication_pipeline.py news_collector/serving/api.py news_collector/system/reporting.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none (builds on backend plan 109's sequential batch and
  plan 045's measured ranked-query work — read both results first; this
  plan must not re-litigate 045's rejected index)
- **Category**: perf
- **Planned at**: commit `04016ca`, 2026-10-11
- **Issue**: omit

## Why this matters

Four backend perf defects with a correctness edge: every frontend webhook
callback (`reject_`/`complete_publication_attempts`) loads ALL in-flight
`publishing` rows into ORM objects to transition a handful of named ones —
a full-table read that worsens exactly when publishing throughput is
highest; the export ranking query orders by `(final_score, collected_date)`
with no id tiebreak while the serving API already uses the 3-key order —
tied rows flip nondeterministically across runs, changing shortlist
selection and downstream publish identity; legacy category/rescore reads
hydrate unbounded ORM sets while keyset-paginated variants already exist;
and the plan-109 batch builds full collaborators (config, editor agents,
DB managers) per item sequentially. Read-only query fixes first (LOW
risk), collaborator hoisting second (MED risk, profiled).

## Current state

Facts (all verified 2026-10-11):

```python
# article_repository.py:365-376 + :431-441 — full in-flight scan, Python filter
candidates = (
    session.query(Article)
    .filter(Article.processing_status == "publishing")
    .all()
)
for article in candidates:
    metadata = article.article_metadata or {}
    refinery_id = (metadata.get("publication") or {}).get("refinery_id")
    if refinery_id not in wanted:
        continue
```

```python
# article_repository.py:1214-1218 — no id tiebreak on the export path
query.order_by(desc(Article.final_score), Article.collected_date.desc())
# vs serving/api.py:1039-1043 — the proven 3-key order:
query.order_by(score_column.desc(), Article.collected_date.desc(), Article.id.desc())
# same gap at get_articles_by_category :1227-1235.
```

```python
# article_repository.py:1260-1270 — unbounded legacy rescore sweep
# (keyset variants exist at :1287-1353 but these callers never use them;
# serving/api.py:976-993 shows the explicit-projection fix pattern)
```

```python
# publication_pipeline.py:866-886 batch loop — docstring is explicit:
# "Each pipeline call builds its own collaborators (config, editor agent,
# DB manager), so per-item cost is ~1x a single publish"
# loop :878-898 awaits each run_publication_pipeline fully, sequentially.
```

Prior related (do not duplicate/re-litigate): plan 109 (sequential ≤5
batch, DONE); plan 045 (measured ranked-query optimization; proposed
cursor index REJECTED by evidence — DESC + coalesce() ORDER BY defeats
index ordering; retained grouped subquery). The tiebreak append here is
safe under 045's evidence (extra key narrows ordering; no index claim).

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Bootstrap | `make bootstrap`         | declared   | exit 0              |
| Lint      | `make lint`              | declared   | exit 0              |
| Type      | `make type`              | declared   | exit 0              |
| Unit      | `make test`              | declared   | pass                |
| Boundaries | `make test-boundaries`  | declared   | pass                |
| Perf      | `make perf`              | declared   | pass (no regression) |

## Scope

**In scope** (the only files you should modify):

- `news_collector/storage/article_repository.py` (SQL-side refinery_id
  filter; id tiebreaks; route legacy callers to keyset/projection reads)
- `news_collector/logic/workflows/publication_pipeline.py`
  (hoist shared collaborators out of the per-item call)
- `tests/` (transition, ordering, pagination tests; batch profile numbers)

**Out of scope** (do NOT touch, even though they look related):

- Ranked-query index/shape changes — plan 045 decided by evidence; the
  tiebreak is ordering-only.
- `refinery_id` as a real indexed column — long-term note only (see
  Maintenance); the `json_extract` predicate is this plan's fix.
- Batch parallelism/fan-out — plan 125 owns enrichment concurrency; this
  plan keeps sequential per-item isolation.
- Headless per-article save N+1 (`headless_collector.py:216` path) —
  real but unmeasured at current volume: investigate, don't fix (record
  the measurement in the commit if you take one).

## Git workflow

- Branch: `advisor/124-publication-perf`
- Commit per step (query fixes, then collaborator hoisting).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Baseline + prior-plan review

Run `make lint && make type && make test-boundaries`. Read plan 109's
batch shape and plan 045's evidence (coalesce/index finding) so nothing
here contradicts them. Profile one batch (5 items) and one webhook
callback transition before changing anything — record wall-clock/SQL counts.

**Verify**: gates green; baseline numbers written down.

### Step 1: Filter publication transitions in SQL

Add `Article.article_metadata['publication']['refinery_id'].IN_(...)` (via
`json_extract` on the metadata path, matching the repo's SQLAlchemy
dialect usage — check how other JSON predicates in this file are written
first) to both transition queries so only named attempts load.
Transition semantics/idempotency unchanged; existing callback tests cover it.

**Verify**: `make test-boundaries` passes; callback tests green; probe
with N in-flight rows shows only named rows loaded (assert via query-count
or the test's existing seam — don't invent ORM internals).

### Step 2: Append the id tiebreak

Add `Article.id.desc()` as third order key in `get_articles_by_score`
(and audit `get_articles_by_category` — same one-line fix). Add an ordering
test with tied `(score, collected_date)` rows asserting deterministic order
matching the serving API's 3-key sequence.

**Verify**: ordering test passes; `make test` passes; export shortlist
(`system/reporting.py:86-90` path) deterministic across two runs on tied fixtures.

### Step 3: Migrate legacy unbounded reads

Route `get_articles_by_category` consumers to limit/keyset reads and the
explicit-projection pattern (`serving/api.py:976-993`); deprecate or delete
the unbounded `get_completed_articles_for_rescoring` once no caller
remains (verify zero callers via grep before deleting — if any remain,
migrate them, don't orphan them).

**Verify**: no caller of the deleted/deprecated variant remains
(`grep -rn "get_completed_articles_for_rescoring\|get_articles_by_category" news_collector/ apps/`);
`make test-boundaries` passes.

### Step 4: Hoist batch collaborators (profile-guided)

Profile first (Step-0 numbers): build collaborators once in
`run_publication_batch`, inject per item; keep per-item error isolation
identical. Review each collaborator for cross-item state leakage (config /
editor / DB scoping — document the scoping decision per collaborator in
code comments). If profiling shows setup tax is negligible (<10% of batch
time), SKIP the hoist, record the numbers, and close the step as
measured-not-worth-it.

**Verify**: batch wall-clock improves (record before/after) OR documented
skip with numbers; `make test-boundaries` passes; per-item outcomes
byte-identical on fixtures.

### Step 5: Full gates + perf

Run `make lint && make type && make test && make test-boundaries && make perf`.

**Verify**: all green, no perf regression.

## Test plan

- Transition tests: only named rows transition; unnamed in-flight rows untouched.
- Ordering test: tied rows deterministic, matching API order.
- Pagination tests: keyset reads return identical pages to legacy reads on fixtures.
- Batch: profile numbers before/after (or documented skip).
- Verification: `make test-boundaries` + `make perf` green.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n 'processing_status == "publishing"' news_collector/storage/article_repository.py` sites all carry the refinery_id predicate (verify each of the two functions)
- [ ] `Article.id.desc()` present in `get_articles_by_score` (+ category variant)
- [ ] No remaining callers of unbounded legacy variants (or explicit deprecation + migrated callers)
- [ ] `make lint && make type && make test && make test-boundaries && make perf` all pass
- [ ] `git diff --name-only 04016ca...HEAD` lists only the in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- The `json_extract` predicate doesn't fit the repo's SQLAlchemy
  dialect/usage (report; the indexed-column migration is explicitly out of scope).
- Step-4 profiling shows negligible setup tax (skip + record — don't hoist for style).
- Any collaborator shows cross-item state leakage on review (report which; don't share it).
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

For the human/agent who owns this code after the change lands:

- **Deferred:** promote `refinery_id` to a real indexed column (kills the
  JSON predicate entirely) — schema migration, unblocked by nothing but
  appetite; revisit when in-flight volume grows 10×.
- If pagination is added to the transition endpoints, the predicate here
  must stay (don't regress to load-all-filter-later).
- Reviewers: scrutinize Step-4 scoping comments — shared mutable
  collaborators across batch items are the top regression risk in this plan.
