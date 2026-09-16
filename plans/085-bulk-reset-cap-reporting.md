# Plan 085: Report bulk-reset cap truncation explicitly instead of silently dropping ids

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat e77a039..HEAD -- apps/refinery/bulk_helper.py news_collector/serving/api.py news_collector/contracts/admin.py tests/unit/refinery/test_bulk_helper.py tests/test_serving_admin_api.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `e77a039`, 2026-09-16

## Why this matters

`POST /v1/admin/content/bulk-reset` (batch_cap=5) silently processes only the
first 5 ids when given 6+, returns `failed: []`, yet its `summary` string says
"5 succeeded, 1 failed". The caller cannot learn which ids were ignored, and
the response contradicts itself. This is a silent-item-drop violating LAW-B6
(batch workflows must fail explicitly). After this plan, over-cap ids are
reported in an explicit response field and `failed`/`summary` agree.

## Current state

The relevant files, each with one line on its role:

- `apps/refinery/bulk_helper.py` — `run_bulk` helper + `BulkResult`/`BulkFailure` types (lines 50-109)
- `news_collector/serving/api.py` — bulk-reset endpoint mapping `BulkResult` to the API response (lines 1979-1996)
- `news_collector/contracts/admin.py` — `AdminBulkResetFailure`/`AdminBulkResetResult` contracts (lines 348-356)
- `tests/unit/refinery/test_bulk_helper.py` — existing unit tests for `run_bulk` (exemplar to extend)
- `tests/test_serving_admin_api.py` — API-level admin tests (add endpoint case here)

Excerpts of the code as it exists today:

`apps/refinery/bulk_helper.py:55-57,95-105` — the cap note counts as a failure
in `summary`, and excess items are sliced away with no record of which ids:

```python
@property
def summary(self) -> str:
    return f"{len(self.succeeded)} succeeded, {len(self.failed)} failed"
...
if batch_cap > 0 and len(items) > batch_cap:
    result.failed.append(
        BulkFailure(
            item=None,
            error=(
                f"Batch size {len(items)} exceeds cap {batch_cap}. "
                f"Only the first {batch_cap} items will be processed."
            ),
        )
    )
    items = items[:batch_cap]
```

`news_collector/serving/api.py:1984-1996` — the endpoint drops the `item=None`
note from `failed` but passes `summary` through unchanged:

```python
return AdminBulkResetResult(
    succeeded=[str(item) for item in result.succeeded],
    failed=[
        AdminBulkResetFailure(
            refinery_id=str(item) if item else "",
            error=error,
        )
        for item, error in [
            (f.item, f.error) for f in result.failed if f.item is not None
        ]
    ],
    summary=result.summary,
)
```

`news_collector/contracts/admin.py:348-356`:

```python
class AdminBulkResetFailure(BaseModel):
    refinery_id: str
    error: str


class AdminBulkResetResult(BaseModel):
    succeeded: List[str] = Field(default_factory=list)
    failed: List[AdminBulkResetFailure] = Field(default_factory=list)
    summary: str
```

Repo conventions that apply here:

- Typed boundaries (LAW-B1): the new field goes on the Pydantic contract, not
  as an ad-hoc dict key. See `AdminBulkResetResult` above as the exemplar.
- Per-item outcomes (LAW-B6): every input id must be accounted for across
  `succeeded` + `failed` + the new `not_processed` field.
- Existing test pattern: `tests/unit/refinery/test_bulk_helper.py` tests
  `run_bulk` purely (injected `action`, no I/O). Extend it, don't restructure.

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Install   | `make bootstrap`         | declared   | exit 0 |
| Lint      | `make lint`              | declared   | exit 0 |
| Type      | `make type`              | declared   | exit 0, ratchet passes |
| Tests     | `make test`              | declared   | all pass |
| Boundaries| `make test-boundaries`   | declared   | all pass |

**Provenance**: `declared` means read from `Makefile`/CI config but not run
(the advisor is forbidden from installing in the user's tree). A `declared`
command that fails on an unmodified checkout is a broken baseline — see Step 0.

## Scope

**In scope** (the only files you should modify):

- `apps/refinery/bulk_helper.py`
- `news_collector/contracts/admin.py`
- `news_collector/serving/api.py` (bulk-reset endpoint only, ~lines 1971-1996)
- `tests/unit/refinery/test_bulk_helper.py`
- `tests/test_serving_admin_api.py` (add cases only)

**Out of scope** (do NOT touch, even though they look related):

- `apps/refinery/published_content.py` — reset logic itself is correct; only reporting changes.
- Any other endpoint using `run_bulk` — check callers, but do not change their behavior unless they share the exact summary/failed contradiction (if they do, report it, don't expand scope).
- The `batch_cap=5` value itself — not under review.

## Git workflow

- Branch: `advisor/085-bulk-reset-cap-reporting`
- Commit per step or logical unit; message style: conventional commits, e.g.
  `fix(refinery): report over-cap bulk-reset ids explicitly` (see `git log --oneline`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run the `Install` row, then `Lint`, `Type`, `Tests` *on the unmodified
checkout*.

- If they all pass: record that, proceed to Step 1.
- If a `declared` command does not exist or fails on the unmodified checkout:
  **STOP and report it** — include the command and exact output. Do not "fix"
  the build to get moving.

**Verify**: every command in the table runs and matches its expected result
on the unmodified checkout.

### Step 1: Expose truncated items from `run_bulk`

In `apps/refinery/bulk_helper.py`:

1. Add a `truncated: list[T]` field (default empty) to `BulkResult`.
2. In `run_bulk`, before slicing, store the dropped items:
   `result.truncated = items[batch_cap:]` (when capped; else leave empty).
3. Change `summary` to count only real items:
   `f"{len(self.succeeded)} succeeded, {real_failures} failed"` where
   `real_failures = sum(1 for f in self.failed if f.item is not None)`,
   and append `", N not processed (over cap)"` when `self.truncated` is non-empty.
4. Keep `all_succeeded` semantics unchanged (cap note is still a warning, not
   a failure).

**Verify**: `.venv/bin/python -m pytest tests/unit/refinery/test_bulk_helper.py -q` → all pass (existing tests unchanged so far; `summary` strings for the
non-capped cases in that file, e.g. `"3 succeeded, 0 failed"`, must still match).

### Step 2: Add `not_processed` to the API contract

In `news_collector/contracts/admin.py`, add to `AdminBulkResetResult`:

```python
not_processed: List[str] = Field(default_factory=list)
cap_note: Optional[str] = None
```

(Additive only — existing fields untouched, so Astro clients keep working.)

**Verify**: `.venv/bin/python -c "from news_collector.contracts.admin import AdminBulkResetResult; print(AdminBulkResetResult(succeeded=[], summary='x').model_dump())"` → shows the new keys with defaults.

### Step 3: Populate the new fields in the endpoint

In `news_collector/serving/api.py` bulk-reset handler (~line 1984):

```python
return AdminBulkResetResult(
    succeeded=[str(item) for item in result.succeeded],
    failed=[...],  # unchanged comprehension
    not_processed=[str(item) for item in result.truncated],
    cap_note=next((f.error for f in result.failed if f.item is None), None),
    summary=result.summary,
)
```

**Verify**: `make lint` → exit 0.

### Step 4: Add regression tests

1. `tests/unit/refinery/test_bulk_helper.py`: over-cap case — 6 items, cap 5:
   assert 5 processed, `result.truncated == [6th]`, summary mentions not-processed,
   `all_succeeded is True` (cap note still a warning).
2. `tests/test_serving_admin_api.py`: bulk-reset with 6 ids → `failed == []`,
   `not_processed` lists the 6th id, `summary` consistent. Model on neighboring
   bulk-reset tests in that file.

**Verify**: `.venv/bin/python -m pytest tests/unit/refinery/test_bulk_helper.py tests/test_serving_admin_api.py -q` → all pass, including the 3+ new tests.

### Step 5: Run the full gates

**Verify**: `make lint && make type && make test && make test-boundaries` → all exit 0.

## Test plan

- New unit tests in `tests/unit/refinery/test_bulk_helper.py` (over-cap truncation list, summary wording, `all_succeeded` unchanged).
- New API test in `tests/test_serving_admin_api.py` (6-id reset → explicit `not_processed`, no silent drop, summary/failed agreement).
- Pattern files: existing tests in both files (no new harness needed).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `make lint` exits 0
- [ ] `make type` exits 0
- [ ] `make test` exits 0; new truncation tests exist and pass
- [ ] `make test-boundaries` exits 0
- [ ] Manual probe: bulk-reset with 6 ids returns the 6th id in `not_processed` and `failed == []` with a consistent `summary`
- [ ] `git diff --name-only e77a039...HEAD` lists only the in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- A step's verification fails twice after a reasonable fix attempt.
- Another `run_bulk` caller depends on `summary` counting the cap note as a failure (grep `\.summary` on `BulkResult` first; if a second consumer exists, report instead of changing shared semantics silently).
- The fix appears to require touching an out-of-scope file.
- A command marked `declared` does not exist or fails on an unmodified checkout (Step 0).

## Maintenance notes

- If `batch_cap` ever becomes configurable per-endpoint, the `cap_note` text must include the effective cap (it already does via `run_bulk`).
- Reviewers: check that no Astro client parses `summary` with a regex expecting exactly two numbers.
- **Deferred:** auditing other `run_bulk` call sites for the same contradiction — unblocked, just out of scope; grep `run_bulk(` to find them.
