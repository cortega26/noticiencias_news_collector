# Plan 060 / Phase 3a todo: Additive durable lifecycle schema (migration only)

Execution index for [`spec.md`](spec.md). The spec's baseline verification,
conventions, scope boundary ("what this phase is NOT"), STOP conditions, and
acceptance criteria are binding; do not implement from this checklist alone.

## Step 0 — baseline

- [x] Confirm current Alembic head is still `b61c2d3e4f50` (re-run
      `ScriptDirectory.from_config(cfg).get_heads()` — the spec's baseline
      may have drifted since this plan was written).
- [x] `pytest tests/test_database_migrations.py -v` passes on an
      unmodified checkout.
- [x] Read `article_repository.py:285-330` and `:420-460` (current
      publication/audit JSON shape) and `:1405-1440` (delete paths) before
      designing FK behavior — the spec's `ondelete="RESTRICT"` decision
      and its reasoning are already made; read this to understand why,
      not to re-decide it.
- [x] Provisionally test-enable `PRAGMA foreign_keys=ON` locally and run
      the full suite to check for latent FK violations elsewhere in the
      schema (per spec.md's STOP condition) BEFORE writing the migration
      — resolve this first, it affects how Step 2 is written.

## Step 1 — five new tables

- [x] `workflow_runs` added: `id`, `run_type`, `status`, `started_at`,
      `finished_at`, `metadata`, `created_at`.
- [x] `workflow_stage_attempts` added: `id`, `workflow_run_id` (FK),
      `stage_name`, `attempt_number`, `status`, `started_at`,
      `finished_at`, `error_code`, `details`, `created_at`.
- [x] `editorial_decisions` added: `id`, `article_id` (FK, nullability
      resolved per spec.md's STOP condition), `decision_type`, `outcome`,
      `reason`, `decided_at`, `details`, `created_at`.
- [x] `publication_attempts` added (ORM class `PublicationAttemptRecord`,
      not `PublicationAttempt`/`PublicationAttemptSummary` — naming
      collision avoidance per spec.md): `id`, `article_id` (FK),
      `refinery_id`, `attempt_number`, `state`, `pr_url`, `branch_name`,
      `started_at`, `finished_at`, `details`, `created_at`.
- [x] `publication_events` added: `id`, `publication_attempt_id` (FK),
      `event_type`, `occurred_at`, `details`, `created_at`.
- [x] All five use `Mapped[...]`/`mapped_column(...)` typed-declarative
      style matching `Article`, not legacy `Column(...)` style.
- [x] Alembic revision `down_revision = "b61c2d3e4f50"`.
- [x] Corresponding ORM model classes added to `models.py` (required for
      `create_all` fresh-DB path to match Alembic's `upgrade head` path).

## Step 2 — constraints, indexes, partial unique index

- [x] FK `ondelete="RESTRICT"` (or SQLite's enforced-equivalent) on
      `article_id`/`workflow_run_id`/`publication_attempt_id` — per
      spec.md's resolved decision, not `CASCADE`/`SET NULL`.
- [x] `PRAGMA foreign_keys=ON` enabled in `DatabaseManager` if Step 0's
      check found it safe to do so (and documented if not, per the STOP
      condition).
- [x] Named `CheckConstraint`s (`ck_<table>_<column>`) on every fixed-
      vocabulary status/state/outcome/event_type/decision_type column,
      matching the `ck_article_status` / `PROCESSING_STATUS_VALUES`
      pattern exactly.
- [x] Lookup indexes on every FK column and every column spec.md marks
      "indexed".
- [x] Unique constraint/index on `workflow_stage_attempts`
      `(workflow_run_id, stage_name, attempt_number)`.
- [x] SQLite partial unique index on `workflow_runs` (`run_type =
      'collection' AND status = '<chosen in-flight value>'`), using
      `sqlite_where=sa.text(...)` matching `2447e261ecf4`'s pattern
      exactly — no `postgresql_where`.
- [x] If any existing test broke from the `RESTRICT` FK (e.g.
      `clear_all_articles` against fixture data with history rows), fixed
      via test setup/teardown ordering, not via loosening the constraint.

## Step 3 — tests

- [x] This revision's ID added to `ALL_REVISIONS` in
      `tests/test_database_migrations.py`.
- [x] This revision's ID added to `REVISIONS_WITH_SUPPORTED_DOWNGRADE`
      (full, correct `downgrade()` written — drops exactly the five new
      tables and their indexes).
- [x] New/extended test: `create_all` fresh DB and `alembic upgrade head`
      from a legacy stamp produce identical table/column sets for the
      five new tables.
- [x] New test: duplicate active `workflow_runs` row
      (`run_type='collection'`, active status) raises `IntegrityError`.
- [x] New test: duplicate `(workflow_run_id, stage_name, attempt_number)`
      in `workflow_stage_attempts` raises `IntegrityError`.

## Step 4 — close out

- [x] `pytest tests/test_database_migrations.py -v` green, including all
      new/parametrized cases.
- [x] `alembic upgrade head` from every `ALL_REVISIONS` entry reaches the
      new head cleanly.
- [x] `alembic downgrade <prev>` → `alembic upgrade head` round-trips
      cleanly for this phase's revision.
- [x] `make test` passes, no regressions elsewhere.
- [x] `git diff --stat` shows only: the new Alembic revision file,
      `news_collector/storage/models.py`,
      `tests/test_database_migrations.py` (plus any test file fixed per
      Step 2's last bullet, named explicitly if so).
- [x] `plans/060/todo.md` Phase 3 checklist: check off exactly the two
      lines spec.md's "Done criteria" section names — no others.
- [x] This file fully checked off.
