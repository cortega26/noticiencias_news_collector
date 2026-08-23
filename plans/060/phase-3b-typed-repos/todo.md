# Plan 060 / Phase 3b todo: Typed repositories, legacy backfill, reconciliation report

Execution index for [`spec.md`](spec.md). The spec's recon findings (read
before starting — especially findings 1, 5, and 6), scope boundary ("what
this phase is NOT"), STOP conditions, and acceptance criteria are binding;
do not implement from this checklist alone.

## Step 0 — baseline

- [x] `pytest tests/test_database_migrations.py tests/unit/storage/ -v`
      passes on an unmodified checkout (Phase 3a's tables/tests already
      merged).
- [x] Confirm locally: querying the real dev DB for
      `article_metadata["publication"]`/`["audit"]` still shows ~0 rows
      (per spec.md finding 6) — if this has changed, the backfill's
      fixture-only testing strategy may need revisiting, report before
      proceeding either way.
- [x] Read `article_repository.py`'s exact `delete_article` except-clause
      structure before touching it (spec.md's fix must catch
      `IntegrityError` specifically, not broaden the existing bare
      `Exception` catch).

## Step 1 — typed repository

- [x] `LifecycleRepository` (or chosen name) created, exposed via direct
      attribute access on `DatabaseManager` (e.g. `db.lifecycle`) — not
      via 1:1 delegate methods (per spec.md finding 2).
- [x] `record_publication_attempt(...)` — append insert; `attempt_number`
      is `COUNT(*) + 1` for the general/future (3c) path, always `1` for
      this phase's backfill specifically (not computed via `COUNT`).
- [x] `transition_publication_attempt(id, *, from_state, to_state,
      **fields) -> bool` — CAS via `UPDATE ... WHERE state = from_state`,
      rowcount-checked, returns `False` on miss (not an exception).
- [x] `record_editorial_decision(...)` — append-only insert, no CAS.
- [x] Read/query methods for **only** `publication_attempts` and
      `editorial_decisions` (the two tables this phase populates) — no
      query methods added for `workflow_runs`/`workflow_stage_attempts`/
      `publication_events`.
- [x] Return types are typed dataclasses (or `NamedTuple`), not ORM
      instances, not raw dicts. Defined in `storage/`, not `contracts/`.

## Step 2 — backfill command

- [x] Location decided (`scripts/` one-shot vs. Alembic data migration) —
      stated and justified against existing precedent.
- [x] `attempt_number=1` always for backfilled rows (not `COUNT(*)+1`).
- [x] Idempotency keyed on `(article_id, refinery_id)` existence check,
      not a row count.
- [x] Missing `refinery_id` in legacy data falls back to `str(article_id)`
      (matching `mark_article_published`'s own existing fallback), not
      skipped or left null.
- [x] Maps `article_metadata["publication"]` → `publication_attempts`
      exactly per spec.md finding 4 (dedicated columns +
      `frontend_checks` → `details`).
- [x] Maps `article_metadata["audit"]` → `editorial_decisions` per
      spec.md finding 4's field placement, with two corrections made
      during execution (both required by Phase 3a's own CHECK
      constraints, not scope creep): `decision_type="auditor"` (spec.md
      said `"audit"`, which the CHECK constraint doesn't allow — only
      `"auditor"`/`"critic"` are valid) and `outcome` mapped through an
      explicit closed vocabulary keyed off the real free-form legacy
      states (`audit_passed`→`pass`, `audit_failed`→`fail`, non-terminal
      states → no row, not `reject`) rather than stored verbatim, since
      the `outcome` CHECK only allows `pass`/`fail`/`accept`/`reject` and
      the legacy `state` field is unconstrained free text.
      `attempts`/`timeout_seconds`/`model`/`endpoint` → `details` as
      planned.
- [x] Idempotent: second run creates zero new rows for
      already-backfilled articles.
- [x] Skips articles with neither key present, no error.
- [x] Does not write anything to `workflow_runs`/`workflow_stage_attempts`/
      `publication_events` — not even placeholder rows.
- [x] Logs a summary (processed / created / skipped / already-migrated
      counts).

## Step 3 — reconciliation report

- [x] Compares every `Article` with legacy `publication`/`audit`
      metadata against the corresponding new-table row(s).
- [x] Distinguishes **drift** (mismatch) from **missing** (legacy exists,
      no new-table row) as separate categories.
- [x] Read-only — no row in any table modified by running the report.
- [x] Exit-code/PASS convention matches existing repo precedent (checked
      against `scripts/verify_gitleaks_checksum_test.sh` or similar).

## Step 4 — `delete_article` fix

- [x] Catches `IntegrityError` specifically, returns `False` with a clear
      log message, article confirmed still present.
- [x] Existing callers re-checked: none depend on the current
      unhandled-exception behavior (STOP condition if one does).
- [x] Test added: delete an article with a
      `publication_attempts`/`editorial_decisions` row → `False`, no
      exception, article still exists.

## Step 5 — tests and close out

- [x] `tests/unit/storage/test_lifecycle_repository.py`: CAS success, CAS
      miss (returns `False`), append-only insert — all against `tmp_path`
      fixture DB.
- [x] Backfill tests (chosen location): both-metadata case, one-only
      case, neither case, idempotency (second run no-ops), partial/
      degraded legacy blob (missing optional key) doesn't crash.
- [x] Reconciliation report tests: clean case, drift case, missing case.
- [x] `delete_article` test from Step 4.
- [x] `make test` passes, no regressions.
- [x] `git diff --stat` shows only the files listed in spec.md's Scope.
- [x] `plans/060/todo.md` Phase 3 checklist: check off exactly the lines
      spec.md's "Done criteria" section names — no others, and do not
      check the dual-write/full-migration-proof lines from this phase
      alone.
- [x] This file fully checked off.
