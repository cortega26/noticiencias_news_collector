# Plan 088: Encode pagination cursors at full float precision

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat e77a039..HEAD -- news_collector/serving/api.py tests/test_serving_api.py tests/perf/test_serving_api_perf.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `e77a039`, 2026-09-16

## Why this matters

`_encode_cursor` formats the score with `:.6f` while the ranked query filters
with `score_column == cursor_score` on full-precision floats. Rows whose scores
differ beyond the 6th decimal are ordered by one key and filtered by a coarser
one, so page boundaries can skip or duplicate rows exactly when scores cluster
(the common case for unscored/zero-score runs). After this plan the cursor
carries the exact score and pagination is stable.

## Current state

The relevant files, each with one line on its role:

- `news_collector/serving/api.py` — cursor codec (`_decode_cursor` lines 228-238, `_encode_cursor` lines 241-245) and ranked query (lines 758-860)

Excerpts of the code as it exists today:

`news_collector/serving/api.py:228-245`:

```python
def _decode_cursor(raw_cursor: str) -> Tuple[float, datetime, int]:
    try:
        decoded = base64.urlsafe_b64decode(raw_cursor.encode("utf-8")).decode("utf-8")
        score_part, collected_part, id_part = decoded.split("|")
        score = float(score_part)
        ...
def _encode_cursor(row: RowType) -> str:
    score = row.final_score or 0.0
    collected = row.collected_date or datetime.now(timezone.utc)
    payload = f"{score:.6f}|{collected.isoformat()}|{row.article_id}"
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("utf-8")
```

`news_collector/serving/api.py:830-847` (approx) — the filter compares the
decoded score for exact equality against the full-precision column, and orders
by `(score desc, collected desc, id desc)`:

```python
and_(
    score_column == cursor_score,
    Article.collected_date < cursor_collected,
),
...
query = query.order_by(
    score_column.desc(),
    Article.collected_date.desc(),
    Article.id.desc(),
)
```

Repo conventions that apply here:

- LAW-B10 + plan 045: pagination must remain deterministic; the structural perf
  gate `tests/perf/test_serving_api_perf.py` pins statement count/payload —
  this change must not add queries or columns.
- Serving pagination semantics are covered by `tests/test_serving_api.py:154-172`
  (stable pagination with sizes 2 and 10) — extend that block.

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Install   | `make bootstrap`         | declared   | exit 0 |
| Lint      | `make lint`              | declared   | exit 0 |
| Type      | `make type`              | declared   | exit 0, ratchet passes |
| Tests     | `make test`              | declared   | all pass |

## Scope

**In scope** (the only files you should modify):

- `news_collector/serving/api.py` (`_encode_cursor` only — plus `_decode_cursor` only if it needs a matching change; it shouldn't)
- `tests/test_serving_api.py` (new cursor tests)

**Out of scope** (do NOT touch, even though they look related):

- The query shape, ordering keys, or projection — plan 045 owns those.
- `nan`/`inf` cursor rejection — a separate unvetted investigate item; do not bundle.
- Admin endpoints' pagination — check whether they share `_encode_cursor` (grep); if they do, they get the fix for free and their tests must pass, but do not otherwise alter them.

## Git workflow

- Branch: `advisor/088-cursor-precision`
- Conventional commits, e.g. `fix(serving): encode cursor scores at full precision`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `Install`, then `Lint`, `Type`, `Tests` on the unmodified checkout. On any
`declared`-command failure on the clean tree: **STOP and report** with exact output.

**Verify**: all commands match their expected results on the unmodified checkout.

### Step 1: Switch the encoder to round-trip precision

In `_encode_cursor`, replace `f"{score:.6f}|..."` with `f"{score!r}|..."`.
`repr(float)` round-trips exactly in CPython, and `float()` in `_decode_cursor`
parses both old (`0.123457`) and new (`0.12345678901234568`) forms, so cursors
issued before the deploy keep decoding — no migration, no version flag.

**Verify**: python REPL round-trip —
`from news_collector.serving.api import _encode_cursor, _decode_cursor` with a
stand-in row object (or the repo's `RowType` factory in tests) asserting
`_decode_cursor(_encode_cursor(row))[0] == row.final_score` exactly for
e.g. `0.1 + 0.2`, `1e-09`, `123.456789012345`.

### Step 2: Add regression tests

In `tests/test_serving_api.py`, next to the stable-pagination block (~lines 154-172):

1. Codec round-trip: scores that differ only past 6dp survive encode→decode exactly.
2. Page-walk stability: seed N rows with near-identical scores (differing at the 9th decimal) and walk the full list via `next_cursor`; assert the union of pages equals the unpaged set with no duplicates and no gaps.
3. Backward compatibility: a cursor encoded in the old `:.6f` form still decodes (hardcode one old-format token, or format with `:.6f` inline in the test).

**Verify**: `.venv/bin/python -m pytest tests/test_serving_api.py -q` → all pass including the 3 new tests.

### Step 3: Run the full gates

**Verify**: `make lint && make type && make test` → all exit 0, and the perf structural gate (`tests/perf/test_serving_api_perf.py`) still passes unchanged.

## Test plan

- New codec round-trip + clustered-score page-walk + old-format compatibility tests in `tests/test_serving_api.py`, modeled on the existing stable-pagination block.
- No new harness; TestClient + seeded DB patterns already in that file.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `make lint`, `make type`, `make test` all exit 0
- [ ] `grep -n ":.6f" news_collector/serving/api.py` → no matches
- [ ] New cursor tests exist and pass
- [ ] `git diff --name-only e77a039...HEAD` lists only the in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- `_decode_cursor` cannot parse the new form (it should — `float(repr(x))` — but if the split/format differs, stop).
- Admin endpoints use a *separate* cursor codec with the same bug (report it; don't expand scope silently).
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

- If the cursor format ever changes incompatibly, old client-held cursors must get a version prefix — this change deliberately avoided that by staying `float()`-parseable.
- Reviewers: confirm no client or test asserts a specific cursor string length/shape from the 6dp era.
- **Deferred:** non-finite (`nan`/`inf`) cursor rejection — unblocked, needs an SQLite semantics check first.
