# Plan 060 / Phase 3c todo: Dual-write into lifecycle tables

Execution index for [`spec.md`](spec.md). The spec's recon findings (read
before starting — especially the state-machine gap, the facade-level
dual-write seam, and the CAS mechanics sections), scope boundaries, STOP
conditions, and done criteria are binding; do not implement from this
checklist alone.

## Step 0 — baseline

- [ ] `pytest tests/test_database_migrations.py tests/unit/storage/ -v`
      passes on an unmodified checkout (Phase 3a/3b already merged).
- [ ] Re-grep the five write-method names against `news_collector/` and
      `apps/` excluding tests/definitions — confirm the call-site table in
      spec.md's Recon section is still exactly right before writing any
      code (STOP condition if a new call site turns up).
- [ ] Read `alembic/versions/2447e261ecf4_*.py` in full (not just the
      excerpt in spec.md) to confirm the exact `batch_alter_table` +
      `drop_constraint`/`create_check_constraint` idiom this repo uses for
      a CHECK-constraint-only change (there may be a cleaner existing
      example than the `sources`/`articles` column-add case cited in
      spec.md — check every migration file's `drop_constraint` calls).
- [ ] Confirm current alembic head is still `effe4ec70d6d` (`alembic
      current` against a scratch copy of `data/news_v3.db`, not the real
      dev DB) before branching the new revision.

## Step 1 — schema migration

- [ ] `PUBLICATION_ATTEMPT_STATE_VALUES` in `models.py` extended to
      `("PUBLISHING", "PR_CREATED", "REJECTED", "COMPLETED")`.
- [ ] New Alembic revision (`down_revision = "effe4ec70d6d"`):
      `batch_alter_table("publication_attempts")` drops
      `ck_publication_attempts_state` and recreates it with the four-value
      expression. No other column/table touched.
- [ ] `upgrade()`/`downgrade()` both idempotency-checked the way
      `2447e261ecf4` does (inspect current constraint state before
      acting), not blind.
- [ ] `downgrade()` does not silently drop or reinterpret any
      `"PUBLISHING"`-state row — raises clearly if one exists rather than
      losing data (per spec.md's additive-only constraint).
- [ ] Migration tested against a **copy** of the real local DB's current
      schema shape (781-article-equivalent, already has Phase 3a tables
      and Phase 3b's backfilled rows) — not just a fresh fixture DB. Never
      run migration commands against `data/news_v3.db` itself.
- [ ] `make migrate` (or equivalent) idempotent on a second run against
      the same scratch copy.

## Step 2 — facade dual-write (`storage/database.py`)

- [ ] `mark_article_publishing`: legacy write unchanged; after it,
      best-effort `self.lifecycle.record_publication_attempt(...,
      state="PUBLISHING", ...)`. Wrapped so a `LifecycleRepository`
      exception is logged, never raised — method's return value/signature
      unchanged.
- [ ] `mark_article_published`: legacy write unchanged; after it, look up
      the latest `PUBLISHING` row for the article (highest
      `attempt_number` if more than one), CAS it to `PR_CREATED`, also
      passing `refinery_id=refinery_id` through `**fields` (defensive
      self-correction — see spec.md's traced `refinery_id` invariant; not
      required by today's call sites but must not be skipped). On CAS
      miss or no `PUBLISHING` row found, fall back to inserting a fresh
      `PR_CREATED` row directly — some row must exist after this call
      succeeds. Same best-effort exception handling as above.
- [ ] Confirm (re-derive, don't just cite spec.md) that both
      `mark_article_publishing`'s and `mark_article_published`'s dual-write
      call sites are gated by the identical `int(article_id)`-succeeds
      condition, so the row created by the first and the row transitioned
      by the second always share the same `refinery_id` string at today's
      call sites — read `refinery_engine.py:354-358` and
      `pr_orchestrator.py:107-114` directly, don't assume.
- [ ] `ArticleRepository.reject_publication_attempts`/
      `complete_publication_attempts` (`article_repository.py:334-418`):
      add an optional keyword-only `on_transition: Callable[[int, str],
      None] | None = None` parameter (article id, refinery id), invoked
      once per article the existing loop actually transitions, using the
      `article.id`/`publication.get("refinery_id")` already in scope
      there. Default `None` — confirm all three existing callers
      (`webhook_handler.py:56`, `webhook_handler.py:104`, `api.py:1062`)
      are passed no new argument and are byte-for-byte unaffected.
- [ ] `DatabaseManager`'s facade `reject_publication_attempts`/
      `complete_publication_attempts`: pass a closure as `on_transition`
      that looks up the article's latest `publication_attempts` row,
      reads its **actual current** `state` (do not assume `PR_CREATED` —
      a webhook can race ahead of `mark_article_published`'s own
      fallback), and CASes it to `REJECTED`/`COMPLETED`. No matching row,
      or a CAS miss → log and return from the closure; must never raise
      back into the repository's loop or affect the legacy transition or
      the method's returned count.
- [ ] `update_article_audit_status`: reuse
      `map_legacy_audit_outcome(audit_status)` from Phase 3b; call
      `record_editorial_decision(decision_type="auditor", ...)` only when
      the mapped outcome is not `None`. Non-terminal legacy states produce
      no row, matching the backfill's existing rule exactly.
- [ ] All five methods: confirmed via direct read that the legacy write
      path executes and its result is returned/used **before** any
      lifecycle-table code runs — dual-write must never gate or delay the
      legacy behavior.
- [ ] `git grep` confirms no other code path bypasses these facade methods
      to call `self.articles.mark_article_publishing`/etc. directly (which
      would skip dual-write silently) — STOP and report if one exists.

## Step 3 — reconciliation report update

- [ ] `scripts/lifecycle_reconciliation_report.py` gets an optional
      `--dual-write-since <ISO date>` flag (no default).
- [ ] When passed, `"missing"` splits into `"missing_pre_dualwrite"`
      (article's `collected_date` before the cutover) and
      `"missing_post_dualwrite"` (on/after) in the JSON output.
- [ ] Omitting the flag reproduces today's exact output shape — existing
      callers/tests of this script must not need changes.
- [ ] Exit code: still 1 if any `"missing_post_dualwrite"` or `"drift"`;
      `"missing_pre_dualwrite"` alone does not fail the run (matches
      today's tolerance for the known pre-backfill gap).

## Step 4 — tests

- [ ] Facade-level unit tests (one per method in Step 2), against a
      `tmp_path` fixture DB: legacy write happens regardless of lifecycle
      outcome; lifecycle row created/transitioned correctly on the happy
      path; a forced `LifecycleRepository` exception is swallowed and
      logged, method still returns its normal value.
- [ ] `mark_article_published`'s CAS-miss/no-PUBLISHING-row fallback path
      explicitly tested (call `mark_article_published` without a prior
      `mark_article_publishing` — matches the real defensive `hasattr`
      caller in `refinery_engine.py`).
- [ ] `reject_publication_attempts`/`complete_publication_attempts`:
      tested against an attempt row left in `PUBLISHING` (webhook races
      ahead of the PR-created transition) to confirm the "read actual
      current state" behavior, not an assumed `PR_CREATED`.
- [ ] `ArticleRepository.reject_publication_attempts`/
      `complete_publication_attempts` called with `on_transition=None`
      (i.e. exactly as today's three existing callers do) produces
      byte-identical behavior/return value to before this phase — a
      regression test, not just an omission.
- [ ] `on_transition` callback itself raising an exception does not
      propagate out of the repository method and does not stop the loop
      from processing remaining articles.
- [ ] Migration upgrade/downgrade round-trip test (Step 1's scratch-copy
      DB).
- [ ] Reconciliation report test for `--dual-write-since` (both buckets,
      flag omitted case unchanged).
- [ ] `make test` passes, no regressions.

## Step 5 — close out

- [ ] `git diff --stat` shows only files named in spec.md's Scope section.
- [ ] `plans/060/todo.md` Phase 3 checklist: check off exactly the two
      lines spec.md's "Done criteria" names — no others.
- [ ] This file fully checked off.
