# Plan 008: Make the validation loop check the bulk-update result (stop the re-fetch / count-inflation failure mode)

> **Executor instructions**: Follow step by step; verify each step. Honor STOP
> conditions. Update this plan's row in `plans/README.md` when done.
>
> **Drift check (run first)**: `git diff --stat b30248f..HEAD -- news_collector/validation/coordinator.py news_collector/storage/article_repository.py`
> If either changed, re-confirm the excerpts; on a mismatch, STOP.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED (changes loop control flow on a batch path)
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `b30248f`, 2026-06-12

## Why this matters

The validation coordinator pulls pending articles in batches, validates them, and persists the new status with `update_validation_status_bulk(...)`. That method **returns `bool`** (`True` on commit, `False` on DB error), but the coordinator **ignores the return value**. Consequences when a batch fails to persist:

1. The articles stay in `pending` status, so the next loop iteration **re-fetches the same batch** and re-validates it — spinning up to `MAX_BATCHES` times.
2. `total_validated += len(pending_articles)` runs every iteration, so the final report **inflates** counts for re-processed batches and reports `"success": True` even though articles were never persisted.

The loop is bounded (`MAX_BATCHES`), so it is not an infinite hang, but it silently wastes work and emits a wrong, falsely-successful report on partial DB failure. The fix: check the persist result and stop with an accurate, failed report.

## Current state

```python
# news_collector/validation/coordinator.py:44-118 (the run loop, abridged)
while True:
    if batch_count >= self.MAX_BATCHES:
        self.logger... .error("Validation halted: Max batches ... Possible infinite loop.")
        break

    pending_articles = self.db_manager.get_pending_articles(limit=self.BATCH_SIZE)
    if not pending_articles:
        break
    batch_count += 1
    ...
    batch_results = self.validator.validate_batch(articles_to_validate)
    total_validated += len(pending_articles)          # <-- counted unconditionally
    ...
    all_mappings = invalid_mappings + valid_mappings
    if all_mappings:
        self.db_manager.update_validation_status_bulk(all_mappings)   # <-- return ignored (line ~103)

self.logger... .info({"event": "validation.completed", "total": total_validated,
                      "rejected": total_rejected, "valid": total_validated - total_rejected,
                      "batches": batch_count})
return {"success": True, "validated_count": total_validated,
        "rejected_count": total_rejected, "details": validation_results}
```

The persist contract:

```python
# news_collector/storage/article_repository.py:746-758  (also database.py:376 delegates here)
def update_validation_status_bulk(self, mappings: List[Dict[str, Any]]) -> bool:
    if not mappings:
        return True
    with self._session() as session:
        try:
            session.bulk_update_mappings(Article, mappings)
            session.commit()
            return True
        except Exception as e:
            logger.error("Error in update_validation_status_bulk: %s", e)
            return False
```

Existing tests: `tests/unit/validation/test_validation_coordinator.py` and `tests/test_validation_loop.py`. Read them first — they show how the coordinator and a fake/mocked `db_manager` are wired, which you will reuse for the new test.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Coordinator tests | `.venv/bin/pytest tests/unit/validation/test_validation_coordinator.py tests/test_validation_loop.py -q` | all pass |
| Lint / type | `make lint && make type` | exit 0 |
| Fast suite | `make test` | all pass |

## Scope

**In scope:**
- `news_collector/validation/coordinator.py` — the persist-result handling in the loop and the returned report
- `tests/unit/validation/test_validation_coordinator.py` (add a failure-path test)

**Out of scope:**
- `update_validation_status_bulk` itself (its `bool` contract is fine).
- `get_pending_articles`, the validator, the adapters.
- Adding ret/retry logic — keep the fix to "detect failure, stop, report accurately."

## Git workflow

- Branch: `advisor/008-validation-persist-check`
- One commit; `fix(validation): …` style.
- Do NOT push or open a PR.

## Steps

### Step 1: Capture and act on the persist result

Where `all_mappings` is persisted, capture the boolean and break the loop on failure, recording that the run did not fully succeed:

```python
persisted = True
all_mappings = invalid_mappings + valid_mappings
if all_mappings:
    persisted = self.db_manager.update_validation_status_bulk(all_mappings)
    if not persisted:
        self.logger.create_module_logger("validation").error(
            {
                "event": "validation.persist_failed",
                "batch": batch_count,
                "mappings": len(all_mappings),
            }
        )
        break
```

Introduce a flag (e.g. `run_failed = False`) before the loop; set it `True` in the `if not persisted:` branch before `break`.

### Step 2: Avoid count inflation

Move `total_validated += len(pending_articles)` so it reflects **persisted** work, or only count after a successful persist. Simplest correct approach: keep the increment where it is but, because you `break` immediately on the first persist failure, the inflated double-count cannot accumulate across many iterations. The remaining requirement is that the **report** reflect failure (Step 3). If the existing tests assert exact `validated_count` semantics, align with them — read them first (STOP guidance below).

### Step 3: Return an accurate report

Change the final return so `success` reflects whether all batches persisted:

```python
return {
    "success": not run_failed,
    "validated_count": total_validated,
    "rejected_count": total_rejected,
    "details": validation_results,
}
```

Keep the existing completion log, but if `run_failed`, the earlier `validation.persist_failed` error already records the cause.

**Verify:** `grep -n "update_validation_status_bulk" news_collector/validation/coordinator.py` shows the result being assigned and checked (not a bare call).

### Step 4: Add a failure-path test

In `tests/unit/validation/test_validation_coordinator.py`, add a test where the fake `db_manager.update_validation_status_bulk` returns `False` for a batch. Assert:
- the loop stops promptly (does not run `MAX_BATCHES` times — e.g. assert the mock was called once),
- the returned dict has `"success": False`.

Also keep/confirm a happy-path test where persist returns `True` and `"success": True`.

**Verify:** `.venv/bin/pytest tests/unit/validation/test_validation_coordinator.py -q` → all pass, including the new failure-path test.

## Test plan

- New test: `test_run_stops_and_reports_failure_when_persist_fails` in `test_validation_coordinator.py`, modeled on the existing coordinator tests' mocking of `db_manager`.
- Confirm `tests/test_validation_loop.py` still passes (it exercises the loop bound / pending fetch).
- Verification: `make test` → all pass.

## Done criteria

ALL must hold:

- [ ] The coordinator assigns and checks the result of `update_validation_status_bulk`
- [ ] On persist failure the loop breaks and the returned report has `"success": False`
- [ ] A new test asserts: persist-failure → single batch attempt + `success False`; happy path → `success True`
- [ ] `make type` exits 0; `make lint` exits 0
- [ ] `make test` exits 0
- [ ] Only `coordinator.py` and its test file modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- The live loop no longer matches the excerpt (e.g. it was already refactored to check the result) — drift; report current behavior.
- An existing test asserts `success: True` / a specific `validated_count` in a way that **encodes the current buggy behavior** — report the conflict; do not weaken the fix to satisfy a test that locks in the bug (it should be updated alongside the fix, but flag it for the reviewer).
- The fix appears to need changes to `get_pending_articles` or the persist method — that is broader than intended; report.

## Maintenance notes

- A natural follow-up (deferred): instead of breaking on first failure, mark the failed batch and continue with the rest, or add a bounded retry. Out of scope here; note it for the owner.
- A reviewer should confirm the report's `success` flag can now be `False` and that downstream callers of this coordinator handle a `False` result (search callers of the coordinator's run method).
