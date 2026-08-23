# Plan 060 / Phase 3a: Additive durable lifecycle schema (migration only)

**Status:** ready to dispatch. Pure additive schema change — no repository
code, no reads, no writes, no production behavior change. Independent of
everything else in plan 060 except that it must land before Phase 3b (typed
repositories + dual-write + backfill), which depends on these tables
existing.

**Relationship to the master plan:** this implements master item 1 (new
tables) and item 2 (constraints/indexes/partial unique index) of
`plans/060/spec.md` "Phase 3: Add durable lifecycle tables and compatibility
projections". Items 3–5 (typed repositories, backfill, dual-write,
consistency report) are `phase-3b-typed-writes` (not yet written — this
phase's scope is deliberately narrow so it can ship first and de-risk 3b).

## Baseline verification (2026-08-23)

Unlike Phase 2's master baseline, this one checked out clean — no
correction needed:

- Current Alembic head is `b61c2d3e4f50`, confirmed via
  `ScriptDirectory.from_config(cfg).get_heads()`, matching the master
  plan's claim exactly.
- Migration chain: `cb486d1d980d` (initial) → `2447e261ecf4` (consolidate
  refinery schema) → `a3f1b2c4d5e6` (content_mode) → `a54ba7f7dabb`
  (blacklist columns) → `b61c2d3e4f50` (score_logs index, head).

## Conventions this phase must follow (established precedent, do not invent new ones)

1. **Partial unique index syntax.** `alembic/versions/2447e261ecf4_consolidate_refinery_schema.py:143-149`
   already does exactly what master item 2 asks for the collections table —
   a SQLite partial unique index via `op.create_index(..., unique=True,
   sqlite_where=sa.text("<condition>"))`. Follow this exact pattern for the
   "one active collection" constraint. Do not add a `postgresql_where`
   clause: `config.toml` only configures `driver = "sqlite"`
   (`[database]` section) — PostgreSQL is a code-level abstraction in
   `news_collector/storage/database.py` that is never actually configured
   anywhere in this repo. Adding Postgres-specific DDL here would be
   untested, unused surface area. If a future phase actually deploys on
   Postgres, that phase adds `postgresql_where` then, with a real
   Postgres CI target to prove it — not this one.

2. **Downgrade support is an explicit opt-in, not automatic.**
   `tests/test_database_migrations.py:238-246` documents that
   `2447e261ecf4`'s `downgrade()` is intentionally incomplete and is
   therefore excluded from `REVISIONS_WITH_SUPPORTED_DOWNGRADE` — the
   codebase does not pretend every migration downgrades cleanly. This
   phase's migration is the easy case: it only adds new tables/indexes
   (no column changes to `articles` or any existing table), so a fully
   correct, complete `downgrade()` (drop the five new tables and their
   indexes, nothing else) is straightforward and must be written. Add
   this phase's revision ID to **both** `ALL_REVISIONS` and
   `REVISIONS_WITH_SUPPORTED_DOWNGRADE` in `tests/test_database_migrations.py`
   — do not follow `2447e261ecf4`'s incomplete-downgrade precedent, that
   precedent exists specifically to document a case this phase is not in.

3. **Naming collision — read before naming anything `PublicationAttempt*`.**
   Two things already carry this name and are NOT what this phase is
   building:
   - `news_collector/logic/workflows/refinery_engine.py`: `self.publication_attempts_dir`
     (a directory of loose JSON files, see "What this phase is NOT" below).
   - `news_collector/contracts/publication_validation.py`: Pydantic
     `PublicationAttemptSummary` / `PublicationAttemptStageResult` — the
     in-memory/file-serialization contract for a single publication
     attempt's outcome, produced by `RefineryEngine._persist_publication_attempt_summary`.
   The master plan names the new table `publication_attempts` — keep that
   table name (it is the correct domain name and matches the master plan),
   but name the SQLAlchemy ORM model class distinctly, e.g.
   `PublicationAttemptRecord` (not `PublicationAttempt` or
   `PublicationAttemptSummary`), so `from news_collector.storage.models
   import PublicationAttemptRecord` never collides or gets confused with
   `from news_collector.contracts.publication_validation import
   PublicationAttemptSummary` in the same file. Do not attempt to unify
   these two concepts in this phase — that's a 3b-or-later question, not
   a schema question.

## What this phase is NOT (scope boundary, read before starting)

**The file-based publication-attempt history is not a rich backfill
source — verify this yourself, don't take it on faith.** As of 2026-08-23,
`data/runtime/publication_attempts/` contains only 20 files (~10 articles'
worth of `<id>.json` + `<id>.frontend_validation.json` pairs), against a
much larger total article count. This directory is overwritten per-attempt
(`_persist_publication_attempt_summary` writes to a fixed path per
article), so it is a **current-snapshot cache, not an append-only log** —
a retried article's earlier attempts are already gone from disk. Do not
design this phase's schema or a later backfill assuming this directory
holds meaningful history; the real (and only) source of legacy state is
each `Article` row's own `processing_status` column and
`article_metadata["publication"]` / `article_metadata["audit"]` JSON
blobs (see `news_collector/storage/article_repository.py:285-330` and
`:420-460` for exactly what shape those blobs take today) — themselves
single-current-state, not history. **This phase does not do any
backfilling** (that's 3b item 4); it only needs to know this so the new
tables' columns are shaped to receive that eventual backfill without
requiring a redesign.

This phase does not touch: `news_collector/logic/workflows/refinery_engine.py`,
`news_collector/storage/article_repository.py`, `news_collector/storage/database.py`,
`news_collector/contracts/publication_validation.py`, any typed repository
code, `frontend_publication_validation.py` (already replaced in Phase 2a —
do not reopen it). No reads or writes to the new tables happen anywhere in
this phase; nothing calls them yet.

## Scope

**Files to touch:**
- One new Alembic revision under `alembic/versions/`, `down_revision =
  "b61c2d3e4f50"`.
- `news_collector/storage/models.py` — five new `Base`-derived ORM model
  classes (see Work below), matching the new tables. Adding model classes
  is required for `DatabaseManager`'s `create_all`-based fresh-DB path
  (used by `test_every_legacy_revision_reaches_head`, per that test's own
  docstring: "DatabaseManager's create_all builds every table this
  codebase's current models declare") to stay consistent with the Alembic
  revision — a table only added via Alembic and not declared as a model
  would make `create_all` and `alembic upgrade head` diverge.
- `tests/test_database_migrations.py` — add the new revision to
  `ALL_REVISIONS` and `REVISIONS_WITH_SUPPORTED_DOWNGRADE`; add coverage
  for the new tables' constraints (see Work, Step 3).

## Work

### Step 1 — five new tables (one Alembic revision)

Add, in a single additive revision:

1. **`workflow_runs`** — one row per pipeline execution (collection run,
   refinery run, etc.). At minimum: `id` (PK), `run_type` (str, indexed —
   e.g. `"collection"`, `"refinery"`), `status` (str), `started_at`
   (datetime, not null), `finished_at` (datetime, nullable), `metadata`
   (JSON, nullable, for anything not worth a column yet).
2. **`workflow_stage_attempts`** — append-only, one row per stage
   execution within a run. `id` (PK), `workflow_run_id` (FK →
   `workflow_runs.id`, indexed), `stage_name` (str, indexed), `attempt_number`
   (int), `status` (str), `started_at`, `finished_at`, `error_code`
   (str, nullable — match the existing convention: `error_code` as a
   stable string, e.g. `"editorial_v2_incomplete"` from
   `GeneratedArticleValidationError`, see Phase 2a), `details` (JSON,
   nullable).
3. **`editorial_decisions`** — append-only, one row per editorial policy
   decision (auditor pass/fail, critic accept/reject, etc.). `id` (PK),
   `article_id` (FK → `articles.id`, indexed — nullable is acceptable if
   a decision can occur before an `Article` row exists, verify against
   `EditorialAuditor`/`EditorialPolicy` call sites before deciding),
   `decision_type` (str, indexed), `outcome` (str), `reason` (Text,
   nullable), `decided_at` (datetime, not null), `details` (JSON,
   nullable).
4. **`publication_attempts`** (ORM class `PublicationAttemptRecord` — see
   naming note above) — one row per publication attempt.
   `id` (PK), `article_id` (FK → `articles.id`, indexed, not null),
   `refinery_id` (str, indexed — matches the existing
   `article_metadata["publication"]["refinery_id"]` concept),
   `attempt_number` (int), `state` (str, indexed — mirror the existing
   state vocabulary already in use: `"PR_CREATED"` etc., see
   `article_repository.py:315`), `pr_url` (str, nullable), `branch_name`
   (str, nullable), `started_at`, `finished_at` (nullable), `details`
   (JSON, nullable).
5. **`publication_events`** — append-only, one row per state-transition
   event on a publication attempt (the actual event log the current
   system has no equivalent of at all — today only the *current* state is
   kept, in `article_metadata["publication"]`). `id` (PK),
   `publication_attempt_id` (FK → `publication_attempts.id`, indexed),
   `event_type` (str, indexed — e.g. `"pr_created"`, `"check_passed"`,
   `"deployed"`, `"rejected"`), `occurred_at` (datetime, not null),
   `details` (JSON, nullable).

Use `Mapped[...]`/`mapped_column(...)` typed-declarative style matching
the existing `Article` model in `models.py`, not legacy `Column(...)`
style, for consistency. Every table gets `created_at`
(`default=lambda: datetime.now(timezone.utc)`) matching the existing
`Article.collected_date` convention.

### Step 2 — constraints, indexes, the partial unique index

- **FK `ondelete` — already resolved, do not re-litigate.** `Article` rows
  ARE hard-deleted in this codebase:
  `news_collector/storage/article_repository.py:1412` (`delete_article`,
  single-row) and `:1429-1438` (`clear_all_articles`, bulk — its own
  docstring calls it "destructive and irreversible", a dev/admin utility).
  Given these history tables exist specifically to preserve an audit
  trail, use `ondelete="RESTRICT"` (or the equivalent no-action default —
  confirm SQLite's actual behavior, since SQLite only enforces FK actions
  when `PRAGMA foreign_keys=ON`, check whether `DatabaseManager` sets that
  pragma) on `article_id`/`workflow_run_id`/`publication_attempt_id` FKs,
  **not** `CASCADE` and **not** `SET NULL`. Deleting an article that has
  real publication/editorial history should fail loudly, not silently
  orphan or erase that history. This does mean `clear_all_articles` (a
  destructive test/dev utility) will now fail if history rows exist for
  an article being bulk-deleted — that is the intended protective
  effect, not a bug to work around; if any existing test relies on
  `clear_all_articles` succeeding against fixture data that also has
  workflow/publication history rows, that test needs to clean up the
  history first, and that test-ordering fix is in scope for this phase
  if it surfaces (see STOP conditions).
- **Check constraints — already resolved, follow this exact precedent.**
  `models.py:42-53` (`PROCESSING_STATUS_VALUES` tuple + `_STATUS_CHECK`
  string) and `models.py:222` (`CheckConstraint(_STATUS_CHECK,
  name="ck_article_status")`) is the established convention: a
  module-level tuple of allowed values, a generated `IN (...)` check
  string, and a named `CheckConstraint`. Do exactly this for every new
  `status`/`state`/`outcome`/`event_type`/`decision_type` column that has
  a fixed vocabulary — name each constraint `ck_<table>_<column>`
  matching `ck_article_status`'s naming.
- Lookup indexes on every FK column and every column named above as
  "indexed".
- Unique delivery key: `workflow_stage_attempts` needs a way to detect a
  duplicate attempt record for the same `(workflow_run_id, stage_name,
  attempt_number)` — add a unique constraint/index on that triple.
- **The SQLite partial unique index for "one active collection" — no
  legacy status flag exists to align with, this is new vocabulary.**
  Searched the codebase for existing collection-run-active tracking:
  none exists yet (the durable `CollectionRunWorkflow` that would use
  this constraint is master Phase 4's "Add the durable
  `CollectionRunWorkflow` and lease/restart recovery" /
  "Return typed 409 for a second active collection" — not built yet).
  This partial index is entirely internal to the new `workflow_runs`
  table: constrain `workflow_runs` to at most one row where `run_type =
  'collection' AND status = '<your chosen in-flight value>'` (e.g.
  `'running'` — pick one value from whatever vocabulary Step 1's
  `workflow_runs.status` check constraint defines, and use that same
  value here; do not invent a second, different status vocabulary for
  this index than the one the check constraint enforces). Follow the
  exact `sqlite_where=sa.text(...)` pattern from `2447e261ecf4` cited
  above. Phase 4 will be the actual consumer of this constraint; this
  phase only needs it to exist and be provably enforced (see Step 3's
  constraint test).

### Step 3 — tests

Add to `tests/test_database_migrations.py`:
- This phase's revision ID added to `ALL_REVISIONS` (proves every legacy
  starting point still reaches the new head) and to
  `REVISIONS_WITH_SUPPORTED_DOWNGRADE` (proves the new downgrade is
  real).
- A new test (or a parametrized extension of an existing one) asserting:
  fresh `DatabaseManager` (via `create_all`) produces the same five new
  tables with the same columns as `alembic upgrade head` does from a
  legacy stamp — this is what keeps `create_all` and Alembic from
  diverging, per Step 1's note above.
- A constraint test: attempting to insert two `workflow_runs` rows with
  `run_type='collection'` and the active status at the same time raises
  an `IntegrityError` (proves the partial unique index actually
  constrains, not just that it was created without error).
- A constraint test: attempting a duplicate `(workflow_run_id, stage_name,
  attempt_number)` in `workflow_stage_attempts` raises `IntegrityError`.

## STOP conditions

- If `EditorialAuditor`/`EditorialPolicy` can produce a decision before
  any `Article` row exists in the DB (i.e. `article_id` would need to be
  nullable on `editorial_decisions`) and this is ambiguous from the code
  — stop and report rather than guessing nullable vs. not-null.
- If adding the five new model classes to `models.py` causes any existing
  test that enumerates/counts tables (grep for `get_table_names()` or
  similar in the test suite) to fail in a way that looks like it encodes
  an assumption this phase should not silently break — stop and report.
- **Confirmed, not hypothetical: `DatabaseManager` does NOT currently
  enable `PRAGMA foreign_keys=ON`** (grepped `database.py`, zero
  occurrences). SQLite silently ignores all FK actions — including this
  phase's new `RESTRICT` constraints — without this pragma. Turning it on
  is the correct fix, but it is **global**: every existing FK in this
  schema (e.g. `ArticleMetrics.article_id`) would start being enforced
  too, not just this phase's new tables, and that's blast radius beyond
  what this phase's declared scope covers. STOP and report before
  deciding: run the existing full test suite with the pragma
  provisionally enabled (a throwaway local check, not a committed change)
  and see whether anything currently relies on FK violations being
  silently ignored elsewhere in the schema. If nothing breaks, enabling
  the pragma in this phase is the right call and should be done (this
  phase's own `RESTRICT` constraints are meaningless otherwise). If
  something breaks, report exactly what and do not enable the pragma
  globally to make this phase's constraints work — that tradeoff is not
  this phase's to make silently.
- If any existing test breaks because `clear_all_articles`'s bulk delete
  now fails against fixture data with history rows (per the `RESTRICT`
  decision above) — fix the test's setup/teardown ordering (delete
  history before articles, or use a distinct fixture without history) as
  part of this phase rather than loosening the FK constraint to make the
  old test pass unchanged.

## Acceptance

- `pytest tests/test_database_migrations.py -v` green, including the new
  parametrized cases (this phase's revision in both lists) and the two
  new constraint tests.
- `alembic upgrade head` from every revision in `ALL_REVISIONS` reaches
  the new head cleanly (existing test, now covering the new revision).
- `alembic downgrade <prev>` then `alembic upgrade head` round-trips
  cleanly for this phase's revision (existing roundtrip test, now
  covering the new revision).
- Fresh DB via `DatabaseManager`'s `create_all` and a legacy DB migrated
  via Alembic produce identical table/column sets for the five new
  tables.
- `make test` passes with no regressions elsewhere.
- `git diff --stat` touches only: the new Alembic revision file,
  `news_collector/storage/models.py`, `tests/test_database_migrations.py`.

## Rollback

Revert the single Alembic revision (`alembic downgrade -1` from this
phase's head, or revert the commit and re-run `alembic upgrade head`
against the reverted chain) — nothing outside these five new, currently
unreferenced tables is touched, so this carries no operational risk. Per
the master plan's own Phase 3 rollback note: "code can return to legacy
readers while additive tables remain" — this phase doesn't even reach the
point of anything reading these tables, so there are no legacy readers to
return to; a revert is strictly simpler here than the master plan's
general case.

## Done criteria (for `plans/060/todo.md` Phase 3 checklist)

This phase closes exactly the schema/constraint half of Phase 3's first
checklist item:
- [ ] Add `workflow_runs`, `workflow_stage_attempts`, `editorial_decisions`,
      `publication_attempts`, and `publication_events` in one or two
      additive Alembic revisions extending current head `b61c2d3e4f50`.
      — closes fully (Step 1).
- [ ] Add check constraints, foreign keys, lookup indexes, unique delivery
      keys, and the SQLite partial unique index that enforces one active
      collection. — closes fully (Step 2).

Do not check these boxes until this phase is merged and independently
verified. The remaining three Phase 3 checklist items (typed repositories,
backfill, dual-write + consistency report) belong to
`phase-3b-typed-writes`, not yet written.
