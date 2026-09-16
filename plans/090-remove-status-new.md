# Plan 090: Remove the impossible admin `status=new` filter

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat e77a039..HEAD -- news_collector/serving/api.py news_collector/storage/models.py tests/test_serving_admin_api.py apps/admin/src`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `e77a039`, 2026-09-16

## Why this matters

The admin triage queue accepts `?status=new`, but the storage CHECK constraint
can never hold `"new"` — the filter always returns an empty page, and any
writer attempting the value gets an `IntegrityError` instead of a valid state.
The comment above the set even claims it "mirrors" storage. Removing the value
(and fixing the comment) eliminates a dead filter and a misleading contract.
Small, safe, and it unblocks honest status-enum work later.

## Current state

The relevant files, each with one line on its role:

- `news_collector/serving/api.py` — `_ADMIN_VALID_STATUSES` + comment (lines 119-124)
- `news_collector/storage/models.py` — `PROCESSING_STATUS_VALUES` CHECK source (lines 42-54)

Excerpts of the code as it exists today:

`news_collector/serving/api.py:119-124`:

```python
# processing_status values the admin triage queue can filter by. Mirrors the
# statuses the storage layer transitions between (pending/new → publishing →
# rejected/completed).
_ADMIN_VALID_STATUSES = frozenset(
    {"new", "pending", "publishing", "rejected", "completed"}
)
```

`news_collector/storage/models.py:42-51`:

```python
PENDING_STATUS = "pen" + "ding"
PROCESSING_STATUS_VALUES = (
    PENDING_STATUS,
    "processing",
    "publishing",
    "validated",
    "completed",
    "error",
    "rejected",
)
```

Note the sets already disagree in both directions (`processing`/`validated`/`error`
are storable but notadmin-filterable; `new` is filterable but not storable).
This plan removes only the impossible value; it does not add the missing ones
(see Deferred).

Repo conventions that apply here:

- Boundary types stay explicit (LAW-B1): the filter set is the contract — change it deliberately, with tests.
- Docs follow code: if the Astro GUI lists `new` as a status option, that reference must be updated in the same change (see Step 1).

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Install   | `make bootstrap`         | declared   | exit 0 |
| Lint      | `make lint`              | declared   | exit 0 |
| Type      | `make type`              | declared   | exit 0, ratchet passes |
| Tests     | `make test`              | declared   | all pass |

## Scope

**In scope** (the only files you should modify):

- `news_collector/serving/api.py` (status set + comment only)
- `tests/test_serving_admin_api.py` (new cases only)
- `apps/admin/src/**` (only if the GUI references a `new` status option — read-only check first, minimal edit if present)

**Out of scope** (do NOT touch, even though they look related):

- `news_collector/storage/models.py` — the CHECK is correct; storage is not changing.
- Adding `processing`/`validated`/`error` to the admin filter set — a separate product decision (see Deferred).
- Any writer/producer of statuses.

## Git workflow

- Branch: `advisor/090-remove-status-new`
- Conventional commits, e.g. `fix(serving): drop impossible admin status=new filter`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `Install`, then `Lint`, `Type`, `Tests` on the unmodified checkout. On any
`declared`-command failure on the clean tree: **STOP and report** with exact output.

**Verify**: all commands match their expected results on the unmodified checkout.

### Step 1: Prove `new` is neither produced nor consumed legitimately

1. `grep -rn '"new"' news_collector/ apps/admin/src/ --include='*.py' --include='*.ts' --include='*.astro' | grep -vi test` — list every production reference to a `new` status.
2. `grep -rn "new" apps/admin/src/lib/types.ts apps/admin/src/lib/api.ts` (if those files define status unions) — check whether the GUI can even send `new`.
3. Confirm how the endpoint rejects unknown statuses today (422? empty page?) — read the filter handler that consumes `_ADMIN_VALID_STATUSES`.

**Verify**: you have a complete list. If ANY producer writes `"new"` to the DB
(it would crash on the CHECK — so expect none) or any GUI flow depends on
filtering by `new` returning something meaningful, that is a STOP condition —
report it.

### Step 2: Remove the value and fix the comment

```python
# processing_status values the admin triage queue can filter by. Must stay a
# subset of storage PROCESSING_STATUS_VALUES (models.py) — values outside the
# DB CHECK can never match.
_ADMIN_VALID_STATUSES = frozenset(
    {"pending", "publishing", "rejected", "completed"}
)
```

If Step 1 found a GUI `new` option, update it to the closest real status or
remove it (same commit, note it in the message).

**Verify**: `make lint` → exit 0.

### Step 3: Add tests

In `tests/test_serving_admin_api.py`:

1. `GET /v1/admin/articles?status=new` → 422 (or whatever the invalid-status path returns — pin the actual code).
2. Each remaining valid status still filters correctly (extend the existing status-filter test if one exists; otherwise one parametrized case).

**Verify**: `.venv/bin/python -m pytest tests/test_serving_admin_api.py -q` → all pass including new tests.

### Step 4: Run the full gates

**Verify**: `make lint && make type && make test` → all exit 0.

## Test plan

- New: `status=new` rejected; valid statuses unaffected.
- Pattern: existing admin-articles filter tests in `tests/test_serving_admin_api.py`.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `make lint`, `make type`, `make test` all exit 0
- [ ] `grep -n '"new"' news_collector/serving/api.py` → no status-set match remains
- [ ] `?status=new` returns the invalid-status code, pinned by a test
- [ ] `git diff --name-only e77a039...HEAD` lists only the in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- Step 1 finds a producer/consumer of `"new"` that would break.
- The endpoint's invalid-status path is itself broken (e.g. 500 instead of 422) — report it; fixing that is plan 091's sibling territory, don't bundle silently. (If it is a one-line mapping fix in the same handler, you may fix it but must call it out in the commit message and final report.)

## Maintenance notes

- The remaining asymmetry (`processing`/`validated`/`error` storable but not filterable) is intentional until triage UX needs those queues.
- Reviewers: check migrations need nothing — no stored value changes, filter-only.
- **Deferred:** exposing `processing`/`validated`/`error` queues in triage — unblocked, needs a GUI decision.
