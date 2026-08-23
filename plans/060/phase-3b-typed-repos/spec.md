# Plan 060 / Phase 3b: Typed repositories, legacy backfill, reconciliation report

**Status:** ready to dispatch. Reads and writes **only** the five tables Phase
3a added — nothing in the existing publication/audit write path changes.
Zero production behavior change to any currently-running code.

**Relationship to the master plan:** this implements master items 3
(typed repositories) and 4 (backfill) of `plans/060/spec.md` "Phase 3:
Add durable lifecycle tables and compatibility projections", plus the
**read-only** half of item 5 (the consistency/reconciliation report). The
**write** half of item 5 — making `mark_article_published`,
`mark_article_publishing`, `reject_publication_attempts`,
`complete_publication_attempts`, and `update_article_audit_status`
actually dual-write into the new tables — is `phase-3c-dual-write` (not
yet written, deliberately separate).

## Why this is split from 3c (dual-write)

Advisor-reviewed judgment call, recorded here so it isn't re-litigated:
the backfill runs once against existing rows; dual-write runs forever
against every new one. If they land in the same phase and the
reconciliation report shows drift, there is no way to tell which one
produced it. Backfill + report is fully testable in isolation — the
report compares new-table rows against `article_metadata`, and that
comparison needs no dual-write in the picture, only the backfill's own
output. 3c depends on this phase's repositories existing (it will call
their write methods) but not on the backfill itself.

## Recon findings that shape this phase (verified 2026-08-23)

1. **No compare-and-set precedent exists anywhere in this codebase.**
   Every existing write method (`mark_article_published`,
   `reject_publication_attempts`, `complete_publication_attempts`,
   `update_article_audit_status` in `article_repository.py`) does a plain
   read-then-write in one session, no version column, no conditional
   `WHERE` guard on the update itself (though `reject_publication_attempts`
   /`complete_publication_attempts` do filter candidates by
   `processing_status == "publishing"` before touching them, which is the
   closest existing analog). **Decision: CAS means `UPDATE ... WHERE
   <state column> = <expected>` with a rowcount check, not a new
   `version` integer column.** This needs no schema change, matches the
   existing semantic pattern, and avoids a second Alembic revision. Do
   not add a `version` column.

2. **The `DatabaseManager` facade is being deprecated in favor of direct
   repository access.** `news_collector/storage/database.py:317-321` has
   an explicit comment: "New code should call the repositories directly:
   `db.articles.save_article(...)` instead of `db.save_article(...)`".
   The new typed repository classes this phase adds should be exposed the
   same way — as attributes on `DatabaseManager` (e.g. `db.lifecycle` or
   split per concern, your call, but state which you chose) — **not** as
   another layer of `DatabaseManager`-delegate methods mirroring every
   repository method 1:1 the way the legacy `Article`/`Source` delegates
   do. That legacy pattern is exactly what the comment says new code
   should stop doing.

3. **New repository return types: dataclasses in `storage/`, NOT Pydantic
   in `contracts/`.** The master plan's "do not expose new cross-package
   `dict[str, Any]` APIs" rules out returning raw dicts, but `contracts/`
   is explicitly cross-repo (per this repo's own `CLAUDE.md`: "Contracts
   (`contracts/frontend_schema.py`) are cross-repo — changes affect the
   frontend"). These new types are pure backend-internal lifecycle
   records with no frontend relevance at all. Putting them in
   `contracts/` would misrepresent them as cross-repo surface even though
   `scripts/check-contract-sync.js` (frontend repo) only actually scans
   `frontend_schema.py` by name and would not technically break — the
   convention violation matters more than the technical non-breakage.
   Use plain typed dataclasses (or `NamedTuple`, match whatever's more
   idiomatic elsewhere in `storage/` — check before picking) defined in
   `storage/`, e.g. `storage/lifecycle_repository.py`.

4. **The `article_metadata` → new-table field mapping is clean — no
   field is genuinely unmappable.** Enumerated both legacy shapes:
   - `article_metadata["publication"]`: `state`, `pr_url`, `refinery_id`,
     `frontend_checks` (nested dict), `updated_at`. Maps to
     `publication_attempts`: `state`, `pr_url`, `refinery_id` go to their
     dedicated columns; `frontend_checks` (no dedicated column) goes into
     `details` JSON.
   - `article_metadata["audit"]`: `state`, `reason`, `updated_at`,
     `attempts`, `timeout_seconds`, `model`, `endpoint`. Maps to
     `editorial_decisions`: `decision_type="audit"` (fixed value —
     this JSON blob only ever records auditor outcomes, never critic/other
     decision types, so there is nothing else to backfill into this
     table), `outcome=state`, `reason=reason`, `decided_at=updated_at`;
     `attempts`/`timeout_seconds`/`model`/`endpoint` (no dedicated
     columns) go into `details` JSON.
   Neither blob needs to drop anything — "preserve unknown legacy values
   rather than guessing" is satisfiable in full via the `details` JSON
   columns 3a already added specifically for this purpose.

5. **`workflow_runs`, `workflow_stage_attempts`, and `publication_events`
   CANNOT be backfilled — say this plainly, do not overpromise.**
   `workflow_stage_attempts.workflow_run_id` is a non-null FK to
   `workflow_runs`, but no legacy data anywhere records a "run identity"
   for historical processing — `article_metadata` has no concept of a
   run, only per-article current state. Synthesizing placeholder
   `workflow_runs` rows to attach backfilled data to would be inventing
   data the master plan's own "preserve unknown legacy values rather than
   guessing" clause forbids. Likewise `publication_events` has nothing to
   backfill from: `article_metadata["publication"]` only ever recorded
   the *current* state, never a transition log, so there is no legacy
   event history to reconstruct. **This phase's backfill populates only
   `publication_attempts` and `editorial_decisions`. `workflow_runs`,
   `workflow_stage_attempts`, and `publication_events` start and remain
   empty after this phase** — they only ever get populated by genuinely
   new activity, which is out of this phase's scope (3c dual-writes
   article-state transitions into `publication_attempts`/
   `editorial_decisions`; nothing in plan 060 so far instruments
   `workflow_runs`/`workflow_stage_attempts` — that likely arrives with
   Phase 4's `CollectionRunWorkflow`, not this phase).

6. **The local dev database cannot size or validate this phase's
   backfill — do not trust it, and do not test against it as primary
   proof.** There are **four** `.db` files under `data/` in this
   checkout — `news_v3.db`, `news_collector.db`, `news.db`,
   `cache_cognitive.db` — and `config.toml` currently points at
   `news_v3.db` specifically. An operator later deciding which database
   to actually run this backfill against for real needs to know this
   ambiguity exists; do not assume `news_v3.db` is the only or correct
   target without confirming against whatever a real deployment actually
   uses. `news_v3.db` has 781 real `Article` rows, but **zero** have
   `article_metadata["publication"]` or `["audit"]` set, and
   `published_at`/`published_url` are null on every row —
   despite the frontend repo genuinely holding real, dated, sourced
   published posts. This local copy is evidently a dev/collection-only
   database that has never been the one recording real publication
   history (or was reset after that history existed) — it is not
   representative of whatever database a real deployment actually uses.
   **Consequence for this phase: prove the backfill and report correct
   via synthetic fixture data with known `article_metadata` shapes (both
   populated and absent), not by running against local data and observing
   an empty, trivially-"clean" result** — an empty backfill against empty
   legacy data would report zero drift regardless of whether the mapping
   logic is actually correct, which proves nothing. This matches how
   `tests/test_database_migrations.py` already tests exclusively against
   `tmp_path` fixture databases, never the real one — follow that
   convention here too.

## What this phase is NOT

- Does not touch `mark_article_published`, `mark_article_publishing`,
  `reject_publication_attempts`, `complete_publication_attempts`, or
  `update_article_audit_status` — those keep writing only
  `article_metadata` exactly as today. Dual-write is Phase 3c.
- Does not populate `workflow_runs`, `workflow_stage_attempts`, or
  `publication_events` (see recon finding 5).
- Does not touch `frontend_publication_validation.py` (Phase 2a) or
  anything in the frontend repo.
- Does not run the backfill command against the real local database as
  part of this phase's own work — it ships the command and proves it
  correct against fixtures; actually running it for real (idempotent,
  re-runnable, so this is low-risk whenever it happens) is an operator
  decision for after this phase merges, informed by finding 6 above
  (whoever runs it for real should first confirm which database a real
  deployment actually writes to, since local dev data won't show
  anything happening).

## `delete_article`'s IntegrityError mismatch — now genuinely in scope

Phase 3a flagged that `delete_article()` promises `bool` but its
try/except doesn't wrap the commit, so a `RESTRICT` FK violation raises
instead of returning `False`. In 3a this was latent (nothing wrote
RESTRICT-protected rows yet). **This phase's backfill is the first code
that creates real rows in `publication_attempts`/`editorial_decisions`
referencing real `article_id`s — so this stops being latent the moment a
backfilled row exists for an article someone then tries to delete.** Fix
`delete_article()` in this phase: catch `IntegrityError` specifically
(not bare `Exception`, which the existing except-block already does more
broadly further down — check the exact except-clause structure before
editing) and return `False` with a clear log message ("cannot delete
article N: has recorded lifecycle history"), preserving the function's
existing `bool` contract rather than changing every caller. Add a test:
delete an article with a backfilled/inserted `publication_attempts` row,
assert `False` is returned (not an unhandled exception) and the article
still exists.

## Scope

**Files to touch:**
- `news_collector/storage/lifecycle_repository.py` (new) — typed
  repository class(es) for the five new tables (write methods only for
  `publication_attempts`/`editorial_decisions`, since those are the only
  ones with anything to write yet; read/query methods for all five so 3c
  and later phases have something to build on).
- `news_collector/storage/database.py` — expose the new repository as an
  attribute (matching the "direct repository access" convention from
  recon finding 2); fix `delete_article`'s `IntegrityError` handling in
  `article_repository.py` (see above — note this file, not
  `database.py`, actually owns `delete_article`).
- `news_collector/storage/article_repository.py` — the `delete_article`
  fix only. Do not touch any other method in this file.
- A new backfill command/script (location your call — match the existing
  convention: is there a `scripts/` one-shot command pattern already,
  e.g. `scripts/quality_gate_refresh.py`'s structure, or does this belong
  as an Alembic `data migration` step? The master plan says "using a
  deterministic, idempotent migration or explicit one-shot command" —
  either is acceptable; check which fits this codebase's existing
  precedent better before picking, and state which you picked and why).
- A new reconciliation report module/script (location your call, same
  reasoning as above).
- New tests: `tests/unit/storage/test_lifecycle_repository.py`,
  `tests/unit/storage/test_backfill.py` (or similar — match your chosen
  location), `tests/unit/storage/test_reconciliation_report.py` (or
  similar).

## Work

### Step 1 — typed repository with compare-and-set + append-only methods

`LifecycleRepository` (or split further if that reads better — your
call, but keep it in one new file for this phase given the scope):

- **`record_publication_attempt(...)`** — insert a new
  `publication_attempts` row (append pattern: each real attempt is its
  own row). For **new** attempts going forward (3c's concern, not this
  phase's), `attempt_number` is `COUNT(*) + 1` scoped to `article_id`.
  **For this phase's backfill specifically, `attempt_number` is always
  `1`** — see Step 2's note below, this is not ambiguous for backfilled
  rows, only for future real attempts.
- **`transition_publication_attempt(id, *, from_state, to_state,
  **fields) -> bool`** — the CAS method: `UPDATE publication_attempts SET
  state = to_state, ... WHERE id = id AND state = from_state`, return
  `True` iff exactly one row was updated (rowcount check), `False`
  otherwise (already-transitioned or nonexistent — caller decides how to
  handle `False`, this method doesn't raise for a normal CAS miss).
- **`record_editorial_decision(...)`** — append-only insert into
  `editorial_decisions`, no CAS needed (this table is genuinely
  append-only, nothing transitions it in place).
- Query/read methods for **only the two tables this phase populates**
  (`publication_attempts`, `editorial_decisions`) — e.g.
  `get_publication_attempts_for_article`,
  `get_editorial_decisions_for_article` — sufficient for Step 3's report.
  Do **not** add query methods for `workflow_runs`/
  `workflow_stage_attempts`/`publication_events`: nothing populates them
  in this phase, so there is nothing for a query method to return yet;
  whichever future phase first writes to one of those tables adds its
  own read methods alongside that write.
- Return types: typed dataclasses, not the ORM model instances directly
  and not raw dicts (match recon finding 3).

### Step 2 — backfill command

- **`attempt_number` is always `1` for backfilled rows — not
  `COUNT(*) + 1`.** `article_metadata["publication"]` only ever records
  the article's *current* publication state, never a history of prior
  attempts (same underlying reason `publication_events` can't be
  backfilled — see finding 5). There is exactly one legacy publication
  state per article, so every row this backfill creates is attempt 1 by
  construction. Do not compute this via `COUNT(*)`.
- **Idempotency key is existence of a `(article_id, refinery_id)` row in
  `publication_attempts`, not a count.** Using `COUNT(*) + 1` for
  `attempt_number` as the idempotency signal would make a re-run insert a
  second row (`attempt_number=2`) instead of no-op'ing — exactly the bug
  the idempotency test below exists to catch. Check existence first,
  skip if found, insert with `attempt_number=1` if not. Same pattern for
  `editorial_decisions` (check existence for that article/decision_type
  before inserting).
- **`refinery_id` fallback**: `article_metadata["publication"]` may lack
  `refinery_id` if it predates `mark_article_published`'s current
  behavior (that method itself falls back to `refinery_id or
  str(article_id)` — `article_repository.py:317`). The backfill must use
  the same fallback (`str(article_id)`) rather than skip the row or leave
  it null — this is not a case of missing data to preserve-not-guess
  about, it's reconstructing a value the write path itself already
  treats as derivable from `article_id` when absent.
- Reads every `Article` row's `article_metadata["publication"]` and
  `["audit"]` (when present) and maps per recon finding 4 above.
- Skips (does not error on) articles with neither key present — most
  rows, per finding 6, will have neither.
- Logs a summary: how many articles processed, how many
  publication/audit rows created, how many skipped (no legacy data), how
  many already-migrated (idempotency hit).
- Does NOT touch `workflow_runs`/`workflow_stage_attempts`/
  `publication_events` (finding 5) — don't write placeholder/empty rows
  there either, just don't touch those tables at all.

### Step 3 — reconciliation report (read-only)

- For every `Article` row with `article_metadata["publication"]` or
  `["audit"]` set, compare against the corresponding
  `publication_attempts`/`editorial_decisions` row(s) and assert the
  mapped fields match (per finding 4's exact field mapping).
- Report format: your call (JSON summary, matching the pattern other
  backend one-shot proof scripts in this repo use — check
  `scripts/verify_gitleaks_checksum_test.sh` or similar for the
  "PASS"/exit-code convention this repo already established, cited in
  Phase 1's work).
- Must report **drift** (a mismatch) distinctly from **missing** (legacy
  data exists but no new-table row does — i.e. backfill hasn't run yet
  or failed for that article) — these are different situations an
  operator needs to distinguish.
- This is read-only: it must not modify any row in any table.

## STOP conditions

- If any existing test asserts on `DatabaseManager`'s current delegate
  method surface in a way that would make adding a new
  `db.lifecycle`-style attribute (or whatever name you choose) break
  something unrelated — stop and report; this shouldn't happen but
  verify rather than assume.
- `attempt_number` is resolved for this phase's own use (always `1` for
  backfilled rows, per Step 2) — this is not a STOP condition here. The
  `COUNT(*) + 1` path in `record_publication_attempt` exists for 3c's
  future use, not exercised by this phase's backfill; if writing that
  general path surfaces a real ambiguity (e.g. concurrent inserts racing
  the count), stop and report rather than guessing at locking semantics
  this phase doesn't otherwise need.
- If the backfill's idempotency check would require querying against
  `workflow_runs`/`workflow_stage_attempts` (which per finding 5 stay
  empty) in a way that's awkward or wrong — stop and report; the
  intended design avoids this entirely by keying only off
  `publication_attempts`/`editorial_decisions`, so hitting this means a
  design assumption above was wrong.
- If fixing `delete_article` reveals that some existing caller actually
  depends on the current (buggy) unhandled-exception behavior — stop and
  report rather than silently changing behavior a caller relies on.

## Acceptance

- New repository unit tests green: CAS success case, CAS-miss case
  (concurrent/already-transitioned, returns `False` not an exception),
  append-only insert case, all against a `tmp_path` fixture DB (matching
  `test_database_migrations.py`'s convention).
- Backfill tested against **synthetic fixture data** (per recon finding
  6) covering: an article with both `publication` and `audit` metadata,
  an article with only one, an article with neither, an article already
  backfilled (idempotency — second run produces no new rows), and an
  article with a legacy `audit`/`publication` blob missing an optional
  key (proves partial/degraded legacy data doesn't crash the backfill).
- Reconciliation report tested against fixtures: a clean case (matches),
  a drift case (deliberately mismatched, report flags it), a missing
  case (legacy data present, no new-table row, report flags it
  distinctly from drift).
- `delete_article` test: deleting an article with a
  `publication_attempts`/`editorial_decisions` row returns `False`, does
  not raise, article still exists.
- `make test` passes, no regressions.
- `git diff --stat` touches only the files listed in Scope.

## Rollback

Revert this phase's commits. The new repository code and backfill/report
scripts are inert until explicitly invoked — nothing in the existing
pipeline calls them (that's 3c). The `delete_article` fix is the only
behavior change reachable by existing code, and it only changes an
unhandled-exception crash into a documented `False` return — reverting it
returns to the (already-latent, already-a-bug) prior behavior, not to a
known-good state, so reverting that specific piece alone is not
recommended even though it's technically safe to do file-by-file.

## Done criteria (for `plans/060/todo.md` Phase 3 checklist)

This phase closes:
- [ ] Add typed repositories and compare-and-set/append-only transitions.
      — closes fully (Step 1).
- [ ] Deterministically backfill known legacy publication/audit state.
      — closes with an honest scope note: only `publication_attempts`/
      `editorial_decisions` are backfillable from real legacy data (see
      recon finding 5); the other three tables have no legacy data to
      backfill and start empty by design, not by omission.

This phase partially advances (but does not close) the remaining item:
- [ ] Dual-write legacy projections and new records.
- [ ] Add and run the consistency report plus the full migration proof.
      — this phase delivers the **report** (read-only half); "the full
      migration proof" implies dual-write exists and can be verified
      end-to-end, which is 3c's job. Do not check this box from 3b alone.

Do not check any boxes until this phase is merged and independently
verified.
