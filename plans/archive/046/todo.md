# Plan 046 TODO

## Step 1: Identify the real production migration owner
- [x] Inventory deploy routes (K8s/fly/railway/render/Procfile/CI) — none found.
- [x] Report the STOP condition in `docs/database_deployment.md` instead of
      inventing wiring.

## Step 2: Make Alembic the schema authority in tests
- [x] Every legacy revision + empty DB → head (`test_every_legacy_revision_reaches_head`).
- [x] Downgrade → re-upgrade roundtrip for revisions with a complete downgrade.
- [x] Model metadata vs. Alembic-head schema parity
      (`test_model_metadata_matches_alembic_head_schema`).
- [x] Single fully-linear history (`test_alembic_history_is_fully_linear`).
- [ ] PostgreSQL equivalents of the above — **blocked**, see spec.md
      "Second, empirically-discovered STOP".

## Step 3: Read-only application revision guard
- [x] `news_collector/storage/migration_guard.py`: `check_revision()`,
      `RevisionState` (up_to_date/behind/ahead/missing_version_table/unreachable).
- [x] `scripts/check_migration_revision.py`: standalone CLI, distinct exit codes.
- [x] 6 tests, all read-only-verified (table set unchanged after every check).
- [x] Shared `build_database_url()` extracted from `DatabaseManager` so the
      guard and the manager can never silently point at different databases.

## Step 4: Single-owner migration job
- [ ] Compose one-shot migration service — **blocked** on Step 2's PostgreSQL
      gap; prototyped and reverted rather than shipped half-working.
- [ ] Production pre-deploy job — **blocked** on Step 1 (no topology to attach it to).

## Step 5: Backup/rollout/rollback procedure
- [x] Documented in `docs/database_deployment.md` (concurrency, expand/contract,
      apply, verify, rollback) as the target process, explicitly marked
      not-yet-rehearsed.
- [x] Corrected `scripts/migrate.py`'s stale comment.
- [x] Corrected `database.py`'s docstring (no longer claims
      `_run_schema_migrations` runs).
- [x] Rewrote `docs/database_deployment.md` end to end (contradictions, garbled
      text, both STOP findings).
- [ ] Rehearsal on a disposable production-shaped database — **blocked** on
      both Step 1 and the PostgreSQL gap.

## Step 6: Enforce deployment proof in CI
- [ ] Disposable PostgreSQL test in canonical CI — **blocked**, same PostgreSQL gap.

## Verification (all run this session)
- [x] `pytest tests/test_database_migrations.py -q` — 18 passed.
- [x] `pytest tests/unit/storage/test_migration_guard.py -q` — 6 passed.
- [x] `pytest --ignore=tests/e2e_pipeline -q` — 1165 passed, 13 pre-existing
      failures (confirmed identical to `main` via stash A/B), 4 skipped.
- [x] `make lint` — 1 pre-existing failure, confirmed identical to `main`.
- [x] `make type` — 3 pre-existing errors, confirmed identical to `main`.
- [x] `make test-contracts` — 47 passed, coverage gate pre-existing failure,
      confirmed identical to `main`.

## Not done, and why (see spec.md for full detail)
- PostgreSQL-side migration proof, compose migration-test service, CI wiring
  for it, and the production rehearsal: all blocked on three independent,
  pre-existing gaps (no psycopg2 anywhere, dead env vars in
  `docker-compose.yml`'s app services, host-absolute paths in committed
  `config.toml`) discovered empirically while attempting this step. Fixing
  them is out of this plan's scope (new pinned dependency + lockfile
  regeneration, touching another team's working config) — recorded as a
  dedicated follow-up in `docs/database_deployment.md`.
- Production pre-deploy job and rehearsal: blocked on Step 1's STOP
  (no discoverable deployment topology to attach anything to).
- `2447e261ecf4`'s incomplete `downgrade()`: flagged, not rewritten
  (historical, already-applied migration; needs dedicated review).
