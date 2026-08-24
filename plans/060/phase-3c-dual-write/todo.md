# Plan 060 / Phase 3c todo: Dual-write into lifecycle tables

Execution index for [`spec.md`](spec.md). The spec's recon findings (read
before starting — especially the state-machine gap, the facade-level
dual-write seam, and the CAS mechanics sections), scope boundaries, STOP
conditions, and done criteria are binding; do not implement from this
checklist alone.

## Step 0 — baseline

- [x] `pytest tests/test_database_migrations.py tests/unit/storage/ -v`
      passes on an unmodified checkout (Phase 3a/3b already merged). 130
      passed.
- [x] Re-grep the five write-method names against `news_collector/` and
      `apps/` excluding tests/definitions — confirm the call-site table in
      spec.md's Recon section is still exactly right before writing any
      code (STOP condition if a new call site turns up). Found one missed
      call site: `pipeline_e2e.py:873` calls `mark_article_publishing`
      through a `DatabaseManager` instance (the same facade) — not a
      bypass. Evaluated via advisor as non-blocking; spec.md amended with
      a note. See Recon section addendum.
- [x] Read `alembic/versions/2447e261ecf4_*.py` in full (not just the
      excerpt in spec.md) to confirm the exact `batch_alter_table` +
      `drop_constraint`/`create_check_constraint` idiom this repo uses for
      a CHECK-constraint-only change (there may be a cleaner existing
      example than the `sources`/`articles` column-add case cited in
      spec.md — check every migration file's `drop_constraint` calls).
      `2447e261ecf4` has no `drop_constraint`/`create_check_constraint`
      calls at all (only `add_column`/`alter_column`) — grepped all of
      `alembic/versions/*.py` for `drop_constraint|create_check_constraint`
      and the only `CheckConstraint` usage anywhere is inline at
      `create_table` time in `effe4ec70d6d`. No cleaner precedent exists;
      `2447e261ecf4`'s idempotency-check + batch-mode pattern (inspect
      current state, guard before acting) is the only idiom to follow.
- [x] Confirm current alembic head is still `effe4ec70d6d` (`alembic
      current` against a scratch copy of `data/news_v3.db`, not the real
      dev DB) before branching the new revision. Confirmed
      `ScriptDirectory.get_heads() == ('effe4ec70d6d',)`; scratch copy of
      the real dev DB (781 articles) made at
      `/tmp/.../scratchpad/phase3c_realshape.db`, its `alembic_version`
      table also reads `effe4ec70d6d`. Note: all five Phase 3a lifecycle
      tables are empty (0 rows) on the real dev DB — Phase 3b's backfill
      was apparently never run against it (only against fixtures/scratch,
      per that phase's own scope). Doesn't block this phase.

## Step 1 — schema migration

- [x] `PUBLICATION_ATTEMPT_STATE_VALUES` in `models.py` extended to
      `("PUBLISHING", "PR_CREATED", "REJECTED", "COMPLETED")`.
- [x] New Alembic revision (`down_revision = "effe4ec70d6d"`):
      `batch_alter_table("publication_attempts")` drops
      `ck_publication_attempts_state` and recreates it with the four-value
      expression. No other column/table touched. Revision id
      `a4d9a4ba00aa` (`alembic/versions/a4d9a4ba00aa_extend_publication_attempts_state_check.py`).
- [x] `upgrade()`/`downgrade()` both idempotency-checked the way
      `2447e261ecf4` does (inspect current constraint state before
      acting), not blind. Uses `inspector.get_check_constraints(...)` to
      read the actual current SQL text and no-ops if already in the
      target state.
- [x] `downgrade()` does not silently drop or reinterpret any
      `"PUBLISHING"`-state row — raises clearly if one exists rather than
      losing data (per spec.md's additive-only constraint). Verified: with
      one PUBLISHING row present, `alembic downgrade -1` raised
      `NotImplementedError` and left the DB unchanged (constraint still
      4-value, 781 articles intact); after deleting the row, downgrade
      succeeded.
- [x] Migration tested against a **copy** of the real local DB's current
      schema shape (781-article-equivalent, already has Phase 3a tables
      and Phase 3b's backfilled rows) — not just a fresh fixture DB. Never
      run migration commands against `data/news_v3.db` itself. Copied the
      main checkout's real dev DB (781 articles, alembic head
      `effe4ec70d6d`) to `/tmp/.../scratchpad/phase3c_realshape.db`;
      pointed `config.toml`'s `[database].path` at that scratch copy only
      for the duration of the test, then reverted `config.toml` via `git
      checkout`. Note: Phase 3a lifecycle tables were all empty (0 rows)
      on the real dev DB — Phase 3b's backfill apparently never ran
      against it, only against fixtures — so "backfilled rows survive"
      wasn't literally exercised against real data, only proven via the
      inserted synthetic PUBLISHING row above and the 133-test unit suite.
- [x] `make migrate` (or equivalent) idempotent on a second run against
      the same scratch copy. `alembic upgrade head` run twice back-to-back
      was a no-op the second time (no output, no error); also covered by
      `tests/test_database_migrations.py::test_alembic_upgrade_head_is_idempotent`
      and the new `test_every_legacy_revision_reaches_head[a4d9a4ba00aa]`.

## Step 2 — facade dual-write (`storage/database.py`)

- [x] `mark_article_publishing`: legacy write unchanged; after it,
      best-effort `self.lifecycle.record_publication_attempt(...,
      state="PUBLISHING", ...)`. Wrapped so a `LifecycleRepository`
      exception is logged, never raised — method's return value/signature
      unchanged. Gated on the legacy call's own return value (advisor
      finding — see spec.md amendment).
- [x] `mark_article_published`: legacy write unchanged; after it, look up
      the latest `PUBLISHING` row for the article (tie-broken by
      `(attempt_number, id)`, not `attempt_number` alone — advisor
      finding, see spec.md amendment), CAS it to `PR_CREATED`, also
      passing `refinery_id=refinery_id` through `**fields` (defensive
      self-correction — see spec.md's traced `refinery_id` invariant; not
      required by today's call sites but must not be skipped). On CAS
      miss or no `PUBLISHING` row found, fall back to inserting a fresh
      `PR_CREATED` row directly — some row must exist after this call
      succeeds. Same best-effort exception handling as above. Gated on
      legacy return value.
- [x] Confirm (re-derive, don't just cite spec.md) that both
      `mark_article_publishing`'s and `mark_article_published`'s dual-write
      call sites are gated by the identical `int(article_id)`-succeeds
      condition, so the row created by the first and the row transitioned
      by the second always share the same `refinery_id` string at today's
      call sites — read `refinery_engine.py:354-358` and
      `pr_orchestrator.py:107-114` directly, don't assume. Re-derived
      independently: `refinery_engine.py:354-358` computes `_numeric_id`
      once and reuses it at line 521 (`mark_article_publishing` gate) and
      passes the *same* `article_id` string through to
      `pr_orchestrator.create_pr(article_id=article_id, ...)` at line 622,
      which does its own `int(article_id)` try/except at
      `pr_orchestrator.py:107-114` before calling
      `mark_article_published(numeric_id, pr_url, article_id)` — confirmed
      it's the same variable, not reassigned in between.
- [x] `ArticleRepository.reject_publication_attempts`/
      `complete_publication_attempts` (`article_repository.py:334-418`):
      add an optional keyword-only `on_transition: Callable[[int, str],
      None] | None = None` parameter (article id, refinery id), invoked
      once per article the existing loop actually transitions, using the
      `article.id`/`publication.get("refinery_id")` already in scope
      there. Default `None` — confirm all three existing callers
      (`webhook_handler.py:56`, `webhook_handler.py:104`, `api.py:1062`)
      are passed no new argument and are byte-for-byte unaffected.
      Advisor finding: the callback is invoked only *after* the
      repository's own `with self._session()` block exits (commit
      already happened) — collected during the loop into a local list,
      dispatched after — so a callback that touches the DB never overlaps
      the still-open legacy transaction. Confirmed all three callers
      unaffected (142 integration/unit tests covering these paths pass).
- [x] `DatabaseManager`'s facade `reject_publication_attempts`/
      `complete_publication_attempts`: pass a closure as `on_transition`
      that **only appends** `(article_id, refinery_id)` to a local list
      (advisor finding — the original "closure does the CAS inline" design
      would open a second session against the same SQLite file while the
      legacy transaction is still open; see spec.md amendment). After
      `self.articles.X(...)` returns, the facade method loops the
      collected pairs and does the "look up latest row for refinery_id,
      read its actual current state (never assume `PR_CREATED`), CAS to
      `REJECTED`/`COMPLETED`" step itself, in `_dual_write_transition`.
      No matching row, or a CAS miss → log and return; wrapped in
      try/except so it can never raise back into the caller or affect the
      legacy transition/returned count.
- [x] `update_article_audit_status`: reuse
      `map_legacy_audit_outcome(audit_status)` from Phase 3b; call
      `record_editorial_decision(decision_type="auditor", ...)` only when
      the mapped outcome is not `None`. Non-terminal legacy states produce
      no row, matching the backfill's existing rule exactly. `details`
      matches `_backfill_audit`'s shape: `{"legacy_state": audit_status}`
      plus `attempts`/`timeout_seconds`/`model`/`endpoint` only when not
      `None`/falsy (advisor finding). Gated on legacy return value.
- [x] All five methods: confirmed via direct read that the legacy write
      path executes and its result is returned/used **before** any
      lifecycle-table code runs — dual-write must never gate or delay the
      legacy behavior. Every facade method calls `self.articles.X(...)`
      first, captures the result/count, and only then touches
      `self.lifecycle`.
- [x] `git grep` confirms no other code path bypasses these facade methods
      to call `self.articles.mark_article_publishing`/etc. directly (which
      would skip dual-write silently) — STOP and report if one exists.
      Re-ran the Step 0 grep after implementing: only definitions
      (`article_repository.py`), the facade delegates
      (`storage/database.py`), and the known call sites (including the
      `pipeline_e2e.py:873` one, which goes through the `DatabaseManager`
      facade, not `self.articles` directly) appear. No bypass found.

## Step 3 — reconciliation report update

- [x] `scripts/lifecycle_reconciliation_report.py` gets an optional
      `--dual-write-since <ISO date>` flag (no default).
- [x] When passed, `"missing"` splits into `"missing_pre_dualwrite"`
      (article's `collected_date` before the cutover) and
      `"missing_post_dualwrite"` (on/after) in the JSON output. Also fixed
      `_check_audit` to compare against the newest `auditor` row
      (`max((decided_at, id))`) instead of `rows[0]` (oldest) — necessary
      once dual-write can append more than one `auditor` row per article
      (advisor finding, see spec.md amendment); otherwise the demo Step 3
      exists to run would report spurious drift.
- [x] Omitting the flag reproduces today's exact output shape — existing
      callers/tests of this script must not need changes. Verified: all 5
      pre-existing tests in `tests/unit/storage/test_reconciliation_report.py`
      pass unmodified.
- [x] Exit code: still 1 if any `"missing_post_dualwrite"` or `"drift"`;
      `"missing_pre_dualwrite"` alone does not fail the run (matches
      today's tolerance for the known pre-backfill gap).
      `ReconciliationSummary.ok()` checks `drift == 0 and missing == 0 and
      missing_post_dualwrite == 0` — `missing_pre_dualwrite` deliberately
      excluded.

## Step 4 — tests

- [x] Facade-level unit tests (one per method in Step 2), against a
      `tmp_path` fixture DB: legacy write happens regardless of lifecycle
      outcome; lifecycle row created/transitioned correctly on the happy
      path; a forced `LifecycleRepository` exception is swallowed and
      logged, method still returns its normal value.
      `tests/unit/storage/test_lifecycle_dual_write.py` (17 tests).
- [x] `mark_article_published`'s CAS-miss/no-PUBLISHING-row fallback path
      explicitly tested (call `mark_article_published` without a prior
      `mark_article_publishing` — matches the real defensive `hasattr`
      caller in `refinery_engine.py`).
      `test_mark_article_published_without_prior_publishing_inserts_fresh_row`
      + `test_mark_article_published_cas_miss_falls_back_to_fresh_row`
      (explicit CAS-miss-via-race variant).
- [x] `reject_publication_attempts`/`complete_publication_attempts`:
      tested against an attempt row left in `PUBLISHING` (webhook races
      ahead of the PR-created transition) to confirm the "read actual
      current state" behavior, not an assumed `PR_CREATED`.
      `test_reject_reads_actual_current_state_not_assumed_pr_created`.
- [x] `ArticleRepository.reject_publication_attempts`/
      `complete_publication_attempts` called with `on_transition=None`
      (i.e. exactly as today's three existing callers do) produces
      byte-identical behavior/return value to before this phase — a
      regression test, not just an omission.
      `test_article_repository_reject_on_transition_none_is_unaffected`.
- [x] `on_transition` callback itself raising an exception does not
      propagate out of the repository method and does not stop the loop
      from processing remaining articles.
      `test_on_transition_callback_exception_does_not_propagate_or_stop_loop`
      (two articles, callback raises on every call, both still transition).
- [x] Migration upgrade/downgrade round-trip test (Step 1's scratch-copy
      DB). `tests/test_database_migrations.py::test_downgrade_upgrade_roundtrip[a4d9a4ba00aa]`
      (parametrized, added to `REVISIONS_WITH_SUPPORTED_DOWNGRADE`) plus
      the manual scratch-DB round-trip in Step 1 (which additionally
      exercised the `NotImplementedError` data-loss guard the automated
      parametrized test doesn't reach).
- [x] Reconciliation report test for `--dual-write-since` (both buckets,
      flag omitted case unchanged).
      `test_reconcile_dual_write_since_splits_missing_into_pre_and_post`,
      `test_reconcile_dual_write_since_pre_only_does_not_fail`,
      `test_reconcile_dual_write_since_omitted_keeps_exact_output_shape`,
      plus `test_reconcile_audit_compares_against_newest_decision_not_oldest`
      for the newest-row fix.
- [x] `make test` passes, no regressions. 1970 passed, 13 skipped
      (pre-existing cross-repo/network-gated skips, unrelated to this
      phase). Also ran (not part of `make test`, but flagged by advisor
      since `pipeline_e2e.py:873` is now a dual-write caller):
      `make test-boundaries` (3 passed) and
      `pytest tests/e2e_pipeline/test_pipeline_e2e.py
      tests/unit/logic/workflows/test_pipeline_e2e_seams.py
      --randomly-dont-reorganize` (22 passed, including the
      `stuck_publishing_recovery` scenario that exercises the seeding
      call). `make lint` and `make type` (coverage ratchet: 86.76% vs
      85.20% baseline) both green.

## Step 5 — close out

- [x] `git diff --stat` shows only files named in spec.md's Scope section.
      Confirmed: `news_collector/storage/{article_repository,database,models}.py`,
      `alembic/versions/a4d9a4ba00aa_*.py`,
      `scripts/lifecycle_reconciliation_report.py`,
      `tests/unit/storage/test_lifecycle_dual_write.py` (new),
      `tests/unit/storage/test_reconciliation_report.py`,
      `tests/test_database_migrations.py`,
      `tests/unit/storage/test_migration_guard.py` (the last two named
      explicitly in spec.md's Scope amendment as a necessary consequence
      of the new head revision), plus `plans/060/phase-3c-dual-write/{spec,todo}.md`
      and `plans/060/todo.md`. No `config.toml` diff (reverted after Step
      1's scratch-DB migration test).
- [x] `plans/060/todo.md` Phase 3 checklist: check off exactly the two
      lines spec.md's "Done criteria" names — no others.
- [x] This file fully checked off.
