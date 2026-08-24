# Phase 3c — dual-write into the durable lifecycle tables

> Part of Plan 060. Depends on Phase 3a (schema, revision `effe4ec70d6d`) and
> Phase 3b (`LifecycleRepository`, exposed as `db.lifecycle`; backfill and
> reconciliation report). Closes master `plans/060/todo.md`'s "Dual-write
> legacy projections and new records" line and the "full migration proof"
> half of the consistency-report line.

## Purpose

Phase 3a built the schema. Phase 3b built typed read/write access and
proved the backfill/reconciliation machinery against fixtures. Neither
phase changed runtime behavior — every write still only touches
`article_metadata`. This phase makes the five publication/audit write
paths **also** write into `publication_attempts`/`editorial_decisions` at
the moment the legacy write happens, so the new tables stop being a
one-time snapshot and start being live workflow evidence — the actual
purpose Phase 3's own spec named.

## Recon findings (this session)

**Call sites** (all under `news_collector/`, excluding definitions and
tests):

| Legacy method | Call site | Moment |
|---|---|---|
| `mark_article_publishing` | `logic/workflows/refinery_engine.py:523` | before git branch/commit, still no PR |
| `mark_article_published` | `logic/workflows/pr_orchestrator.py:114` (`create_pull_request`) | PR just opened |
| `reject_publication_attempts` | `serving/webhook_handler.py:56` | frontend CI/deploy rejected the attempt |
| `complete_publication_attempts` | `serving/webhook_handler.py:104` | frontend CI/deploy succeeded |
| `update_article_audit_status` | `serving/api.py:1030`, `refinery_engine.py:721` | auditor/critic decision recorded |

All five are called exclusively through `DatabaseManager` facade methods in
`storage/database.py` (`mark_article_publishing:403`, `mark_article_published:355`,
`reject_publication_attempts:360`, `complete_publication_attempts:365`,
`update_article_audit_status` near `:380`) — every one of these facade
methods is currently a pure 1:1 delegate to `self.articles.*`. Nothing
calls `ArticleRepository` methods directly from workflow/serving code.
**This is the dual-write seam**: `DatabaseManager` is the only object that
already holds both `self.articles` and `self.lifecycle` (`database.py:177`),
so orchestration belongs in these five facade methods, not inside
`ArticleRepository` (which must stay decoupled from `LifecycleRepository`,
matching Phase 3b's existing separation).

**The state-machine gap.** `PUBLICATION_ATTEMPT_STATE_VALUES` (`models.py:712`)
is `("PR_CREATED", "REJECTED", "COMPLETED")` — a CHECK constraint
(`ck_publication_attempts_state`, `models.py:765`) enforces exactly these
three. There is no state for "publishing started, PR not yet created." But
`mark_article_publishing` exists precisely to cover that window: it sets
`processing_status="publishing"` and stashes `publishing_started_at`/
`publishing_branch` on `article_metadata` *directly* (not under the
`publication` key) so that `get_publishing_state`/`PROrchestrator.attempt_recovery`
(`pr_orchestrator.py:148`) can detect a crash between "started publishing"
and "PR created" and recover instead of silently losing the attempt. A
`publication_attempts` table that only ever gets a row once a PR exists is
blind to exactly the failure mode `attempt_recovery` was built to catch —
the in-flight, not-yet-a-PR attempt. Confirmed via `advisor` before
committing to a design: **extend the CHECK constraint** rather than skip
dual-writing `mark_article_publishing`.

**No legacy vocabulary exists for a pre-PR state.** Checked
`article_repository.py:285-332` (`mark_article_published`) directly: the
only `"state": "pending"` value ever written in this codebase lives under
`article_metadata["publication"]["frontend_checks"]["state"]` — a
different field (frontend CI readiness), not `publication.state`.
`lifecycle_repository.py`'s own module docstring (lines ~50-57) already
notes "`publication_attempts.state`, whose three legacy values already
match `PUBLICATION_ATTEMPT_STATE_VALUES` exactly" — i.e. `mark_article_published`
is the *first* place `publication.state` is ever set, straight to
`"PR_CREATED"`. There is nothing to mirror. This phase adds **new**
vocabulary: `"PUBLISHING"` (matches the existing `UPPER_SNAKE` casing of
the other three values, and matches `processing_status == "publishing"`).
Do not present this as parity with a legacy value — there isn't one.

**A `refinery_id`-equivalent is available at `mark_article_publishing`
time.** `refinery_engine.py:517-523` computes `branch_slug`/`expected_branch`
and has `article_id` in scope before calling `mark_article_publishing` —
the same `article_id` string that `pr_orchestrator.py:108-114` later
passes as `refinery_id` to `mark_article_published`. So the pre-PR row can
be keyed by the same `refinery_id` the eventual PR-created row would use,
letting the two calls be linked by `attempt_id` rather than guessed by
state.

**Migration precedent and safety.** `alembic/env.py` sets
`render_as_batch=True` for sqlite in both `run_migrations_offline` and
`run_migrations_online` (lines 83, 109) — batch mode is already configured,
so a CHECK-constraint change (which SQLite cannot do via plain `ALTER
TABLE`) recreates the table under the hood. `2447e261ecf4` is this repo's
existing precedent for `batch_alter_table` against `sources`/`articles`.
Confirmed `alembic/env.py`'s `run_migrations_online` builds its own engine
via `engine_from_config` (line 96) — a completely separate `Engine`
instance from `DatabaseManager`'s. `DatabaseManager`'s `PRAGMA
foreign_keys=ON` listener is registered as `event.listens_for(self.engine,
"connect")` (`database.py:208`) — scoped to that one engine instance, not
global — so Alembic's own connection never enforces FKs. The incoming FK
from `publication_events.publication_attempt_id` (`ondelete="RESTRICT"`,
`models.py:798`) is therefore not a hazard during the batch recreate: no
active PRAGMA to trip over, and SQLite batch mode disables FK checks for
the duration of the swap regardless.

**CAS mechanics.** `transition_publication_attempt` (`lifecycle_repository.py:234`)
takes an explicit `attempt_id` (primary key) plus `from_state`/`to_state` —
it does not search by `refinery_id`. Callers must know which row they're
transitioning. `record_publication_attempt` (`lifecycle_repository.py:179`)
is append-only: each call inserts a new row with an auto-incrementing
`attempt_number` scoped to `article_id` (or an explicit one). This means a
second `mark_article_publishing` call for the same article after a
recovery timeout correctly produces attempt 2, not a collision — matching
what "attempt" already means in this table.

**`refinery_id` consistency between the two pre/post-PR call sites — traced,
not assumed.** `mark_article_published`'s only call site
(`pr_orchestrator.py:114`) passes the *string* `article_id` it received as
`refinery_id`, and the comment above it (lines 109-113) hedges: "in the
normal, DB-id case they're the same string" as the numeric DB id — implying
a non-normal case exists where they diverge. Traced where that string comes
from: `_resolve_article_identity()` (`refinery_engine.py:77-97`) returns
`str(article_pk)` when `article["id"]` is present, and falls back to the
article's **title** only when there is no DB id at all. Both dual-write call
sites in this phase are gated by `_numeric_id = int(article_id)` succeeding
under `contextlib.suppress(ValueError, TypeError)` (`refinery_engine.py:354-358`,
guarding `mark_article_publishing` at line 521; the identical `int(article_id)`
try/except guards `mark_article_published` at `pr_orchestrator.py:107-114`).
The title-fallback case makes `int(article_id)` raise, so *both* calls are
skipped together — dual-write never fires for that case, matching the
existing legacy behavior (the "publishing" mark itself doesn't fire either
today). In the only branch where dual-write fires, `article_id` is
necessarily `str(article_pk)` by `_resolve_article_identity`'s own logic, so
`str(_numeric_id) == article_id` holds exactly — the pre-PR row's
`refinery_id` and the PR-created call's `refinery_id` are guaranteed
identical at today's call sites. This is a proof, not a coincidence to trust
blindly if a new caller is added later — see Step 2's added defensive
measure below.

**Reconciliation report's "missing" meaning changes.** Right now,
`scripts/lifecycle_reconciliation_report.py`'s `"missing"` classification
means "the backfill hasn't run for this article yet" — expected and
routine before dual-write exists. Once dual-write is live, a `"missing"`
result on an article created *after* this phase ships means something
categorically worse: a dual-write silently failed. The report cannot tell
these apart today. In scope for this phase (see Design below).

## Design

### Schema change — new migration, revision TBD (chain head is `effe4ec70d6d`)

- Extend `PUBLICATION_ATTEMPT_STATE_VALUES` in `models.py` to
  `("PUBLISHING", "PR_CREATED", "REJECTED", "COMPLETED")`.
- New Alembic revision: `batch_alter_table("publication_attempts")`,
  `drop_constraint("ck_publication_attempts_state", type_="check")` +
  `create_check_constraint` with the four-value expression. Follow
  `2447e261ecf4`'s batch pattern; do not touch any other column.
- `downgrade()` restores the three-value constraint. Since this program's
  standing rule is additive-only / no data loss, `downgrade()` must not
  attempt to delete any `"PUBLISHING"`-state rows it can no longer
  represent — raise `NotImplementedError` in `downgrade()` if any such row
  exists (mirror however Phase 3a's own migrations handled irreversibility,
  check that file for the exact pattern before writing this).
- No changes to `publication_events` or any other table.

### Facade-level dual-write (`storage/database.py`)

All five `DatabaseManager` facade methods keep their existing signature,
return value, and legacy write untouched — `reject_publication_attempts`/
`complete_publication_attempts` gain an optional parameter only at the
`ArticleRepository` layer beneath them (see below), not on the facade
methods callers actually use. Dual-write is additive and best-effort: wrapped so a
`LifecycleRepository` failure is logged and swallowed, never raised into
the caller — the legacy write is the source of truth today and must keep
working even if the new tables have a problem. This mirrors the existing
defensive pattern already at `refinery_engine.py:521-528` around the
current `mark_article_publishing` call.

- **`mark_article_publishing(article_id, branch_name)`**: after the
  existing `self.articles.mark_article_publishing(...)` call, call
  `self.lifecycle.record_publication_attempt(article_id, refinery_id=str(article_id), state="PUBLISHING", started_at=<now>, branch_name=branch_name)`.
  Store nothing extra on the `Article` row — the new row's own `id` is
  looked up again in the next call, not threaded through
  `article_metadata` (keeps the legacy schema untouched, per this
  program's own constraint).

- **`mark_article_published(article_id, pr_url, refinery_id=None)`**:
  after the existing legacy write, resolve `refinery_id` the same way the
  legacy code already does (`refinery_id or str(article_id)`). Call
  `self.lifecycle.get_publication_attempts_for_article(article_id)`,
  find the latest row with `state == "PUBLISHING"` (if several — recovery
  can produce more than one — take the highest `attempt_number`). If
  found, `transition_publication_attempt(attempt.id, from_state="PUBLISHING", to_state="PR_CREATED", pr_url=pr_url, refinery_id=refinery_id)`
  — passing `refinery_id` again through `**fields` is defensive, not
  required by today's traced invariant (see the Recon finding above): if a
  future caller ever violates the invariant, the row self-corrects instead
  of drifting silently. On a `False` (CAS miss — race, or already
  transitioned) **or** no `PUBLISHING` row found at all (defensive
  `hasattr` callers can skip `mark_article_publishing`), fall back to
  `record_publication_attempt(..., state="PR_CREATED", pr_url=pr_url, started_at=<now>)`
  directly, so a PR-created event is always represented by some row.

- **`reject_publication_attempts(refinery_ids, reason)`** /
  **`complete_publication_attempts(refinery_ids, deploy_url)`**: these are
  bulk, webhook-driven, and only know `refinery_id`s, not `attempt_id`s. The
  existing `ArticleRepository` implementations (`article_repository.py:334-418`)
  mutate `Article` rows inside their own `with self._session()` loop and
  return only an `int` count — the facade has no way to learn *which*
  articles were transitioned from today's return value, and all three
  existing callers (`webhook_handler.py:56,104`, `api.py:1062`) treat the
  return as a plain count (`updated == 0` checks; `api.py:1062` passes it
  straight into `AdminMutationResult(updated=updated)`), so changing the
  return type to `list[int]` would silently break `updated == 0` at every
  call site (a list is never `== 0`). **Fix: add an optional keyword-only
  callback**, `on_transition: Callable[[int, str], None] | None = None`
  (article id, refinery id), to both `ArticleRepository` methods — invoked
  once per article the existing loop actually transitions, right where it
  already has `article.id` and `publication.get("refinery_id")` in hand.
  Default `None` — every existing caller (all three, untouched) gets
  identical behavior; this is an additive optional parameter, not a fully
  unchanged signature. `DatabaseManager`'s facade passes a closure that
  does the same "look up the article's latest row, read its actual current
  state, CAS to `REJECTED`/`COMPLETED`" as `mark_article_published` above,
  wrapped in the same best-effort try/except. A `False` CAS or no-row-found
  inside the callback logs and returns — it must never raise back into the
  repository's loop, or one bad lifecycle row would abort an otherwise-good
  bulk legacy transition.

- **`update_article_audit_status(...)`**: reuse Phase 3b's existing
  `map_legacy_audit_outcome(audit_status)` — call
  `record_editorial_decision(article_id=..., decision_type="auditor", outcome=mapped, reason=reason, decided_at=<now>, details={...})`
  only when `mapped is not None` (mirrors exactly what the backfill script
  already does for terminal states; non-terminal states like
  `audit_pending`/`audit_skipped*` produce no row, per Phase 3b's own
  documented rule).

### Reconciliation report — distinguish stale-missing from dual-write-missing

Add a cutover marker: the report already reads `article.collected_date`
per row. Once this phase's dual-write ships (call it deploy date D),
`"missing"` on an article with `collected_date >= D` is a **dual-write
failure** (new, actionable); `"missing"` on an article with
`collected_date < D` is the **pre-existing backfill gap** (already known,
routine). Add a `--dual-write-since <ISO date>` CLI flag (no default — an
explicit value the operator passes, e.g. this phase's merge date) that
splits `"missing"` into `"missing_pre_dualwrite"` and
`"missing_post_dualwrite"` in the JSON output; keep exit-code semantics
conservative (still 1 for any `"missing_post_dualwrite"`, unchanged
tolerance for `"missing_pre_dualwrite"`). Omitting the flag keeps today's
behavior exactly (single `"missing"` bucket) — this is additive, not a
breaking change to the script's existing callers/tests.

## Scope boundaries

**In scope:**
- The migration extending `ck_publication_attempts_state`.
- Dual-write in the five `DatabaseManager` facade methods listed above.
- The reconciliation report's `--dual-write-since` split.
- Tests: unit tests per facade method (dual-write happens, CAS
  fallback-to-fresh-row path, best-effort swallow-on-lifecycle-failure
  path, bulk reject/complete look-up-then-CAS path), a migration test
  (upgrade/downgrade round-trip, existing 781-row-shaped fixture data
  survives), and a reconciliation-report test for the new flag.

**Out of scope (do not touch):**
- `workflow_runs`/`workflow_stage_attempts`/`publication_events` — still
  nothing creates a "run" concept; unchanged from Phase 3a/3b's explicit
  scoping-out.
- Any change to `article_metadata`'s shape or the legacy write logic
  itself — dual-write is strictly additive alongside it.
- Running the backfill or reconciliation report against the real local DB
  again — 3b already did this; not this phase's job.
- `apps/admin`/`apps/refinery` — unrelated surface.

## STOP conditions

- If the migration's `batch_alter_table` recreate on `publication_attempts`
  fails against a copy of the real local DB's current schema (781 articles,
  already-backfilled rows from Phase 3b) — stop and report the exact error
  rather than working around it blind.
- If any of the five facade methods has a call site this recon missed
  (re-grep before writing code, not just trusting this doc) — stop and
  report the new call site before deciding how it dual-writes.
- If `_resolve_article_identity`, `refinery_engine.py`'s `_numeric_id`
  derivation, or `pr_orchestrator.py`'s `mark_article_published` call site
  have changed since this recon such that the traced `refinery_id`
  invariant (Recon section) no longer holds — stop and report; do not
  proceed on the assumption it still does.

## Done criteria (maps to master `plans/060/todo.md`)

- [ ] "Dual-write legacy projections and new records" — closed by the
      five facade methods above.
- [ ] "Full migration proof" half of the consistency-report line — closed
      by the reconciliation report's `--dual-write-since` split
      demonstrating dual-write and backfill agree going forward.
