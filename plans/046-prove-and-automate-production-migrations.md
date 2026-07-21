# Plan 046: Prove and automate production database migrations

> **Executor instructions**: Treat the real deployment topology as an explicit prerequisite. Never stamp, auto-upgrade, or test against a production database while discovering how it is deployed. Update plan 046 in `plans/README.md` when complete.
>
> **Drift check (run first)**:
> `git diff --stat e43bd30..HEAD -- alembic alembic.ini scripts/migrate.py news_collector/storage/database.py Dockerfile docker-compose.yml Makefile .github/workflows docs/database_deployment.md tests/test_database_migrations.py`

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: plans/024-canonicalize-backend-dependencies.md, plans/030-lock-developer-toolchains.md
- **Category**: reliability
- **Confidence**: LOW; the repository documents a production pre-deploy migration, but no production deployment manifest or workflow is present to prove who runs it.
- **Planned at**: backend `e43bd30`, 2026-07-21

## Why this matters

Alembic exists and local commands can upgrade a database, but no checked-in deployment path invokes them before collector/refinery startup. Tests mostly exercise SQLite and `create_all`, while active docs contain stale statements about runtime schema repair. Without a proven single migration owner and revision guard, a fresh deploy can start against an old schema or concurrent replicas can race an unsafe upgrade.

## Current state

- `scripts/migrate.py` wraps Alembic `upgrade`, `downgrade`, `current`, and `history`, but its module comments still mention removed runtime `create_all`/schema-repair behavior.
- `Makefile:95-96` exposes manual `migrate`; the local `refinery` target depends on it, but application/container startup does not.
- `Dockerfile` launches the collector directly. `docker-compose.yml` starts collector/refinery after database health without a one-shot migration service.
- `alembic/env.py` derives the URL from `DATABASE_CONFIG`; migrations live under `alembic/versions/`.
- `tests/test_database_migrations.py` upgrades one handcrafted SQLite legacy state and checks columns/indexes created by `DatabaseManager`; it does not prove empty database -> Alembic head, every supported predecessor -> head, PostgreSQL behavior, or deploy ordering.
- No checked-in GitHub workflow invokes `make migrate`, `scripts/migrate.py`, or `alembic upgrade head`; `docs/database_deployment.md` says the production pipeline must do so without identifying such a pipeline.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Revision integrity | `.venv/bin/alembic heads && .venv/bin/alembic history --indicate-current` | exactly one expected head and connected history |
| SQLite migration tests | `.venv/bin/python -m pytest tests/test_database_migrations.py -q` | empty/legacy/head/revision-guard cases pass |
| PostgreSQL migration tests | `docker compose --profile migration-test run --rm migration-test` | disposable PostgreSQL upgrades to head and app readiness succeeds |
| Deployment proof | `.venv/bin/python scripts/verify_migration_deployment.py --compose docker-compose.yml` | one migration owner precedes every DB-consuming service; app services do not auto-upgrade |
| Full backend gates | `make lint && make typecheck && make test && make test-contracts` | exit 0 |

## Scope

**In scope**: deployment-topology inventory, a one-shot/pre-deploy migration command, disposable SQLite/PostgreSQL upgrade tests, Alembic revision/readiness verification, concurrency/backup/rollback documentation, compose wiring, and the actual production pipeline once its owner is found.

**Out of scope**: running against production, stamping an unknown database, app replicas independently calling `upgrade head`, destructive downgrade in production, changing hosting platforms, or adding unrelated schema changes.

## Git workflow

- Branch: `advisor/046-production-migration-proof`.
- Commit example: `ops: enforce single-owner database migrations`.
- Separate safe test/guard changes from deployment-platform wiring; require operator review for the latter.

## Steps

### Step 1: Identify the real production migration owner

Inventory every deploy route outside and inside this repository: container service/job, scheduler, CI/CD provider, host startup command, secrets/identity, replica count, health checks, database engine/version, and rollback mechanism. Record a single accountable pre-deploy migration owner in `docs/database_deployment.md`.

**Verify**: the documented command, working directory, image/commit, identity, timing, failure behavior, and application dependency are observable in the actual deploy configuration.

### Step 2: Make Alembic the schema authority in tests

Replace tests that infer migration safety from `DatabaseManager`/`create_all` with Alembic-first fixtures. Cover empty database -> head, each supported legacy revision -> head, head idempotency, single-head history, metadata-vs-schema comparison, and downgrade only for revisions whose downgrade is declared supported. Keep `create_all` only for isolated unit fixtures, not as deployment evidence.

**Verify**: deleting a migration operation or adding an un-migrated model column fails the suite.

### Step 3: Add a read-only application revision guard

Implement a reusable command/check that compares database `alembic_version` to the packaged head without mutating schema. Wire readiness/startup to fail clearly on behind/ahead/multiple/unknown revisions. Do not expose credentials/revision SQL in public health payloads.

**Verify**: head is ready; behind, ahead, missing version table, and unreachable DB fail with distinct operator-facing diagnostics and no schema writes.

### Step 4: Provide a single-owner migration job

Add a one-shot compose migration service that runs the same pinned application image and completes before collector/refinery start. In the real production platform, add the equivalent pre-deploy job with timeout, retry policy appropriate for non-idempotent DDL, log retention, least-privilege migration credentials, and database-native/advisory locking if the platform can launch duplicates.

**Verify**: two attempted deploys cannot concurrently apply the same revision; migration failure prevents new app startup while the old healthy release remains available according to platform policy.

### Step 5: Define backup, rollout, and rollback procedure

Document preflight/current/head, backup/PITR check, expand-contract rules, migration execution, revision verification, application rollout, observability, and rollback. Prefer forward fixes; require explicit data-loss review before any downgrade. Correct stale `scripts/migrate.py` and active deployment documentation.

**Verify**: rehearse on a disposable production-shaped database from the previous release and record timing, lock impact, app compatibility window, and recovery outcome.

### Step 6: Enforce deployment proof in CI

Add static tests for one migration owner/dependency and disposable PostgreSQL migration tests to canonical CI. Build the image once, run migration job, then start services and assert revision-aware readiness. Preserve artifacts for failures without secrets.

**Verify**: removing the migration dependency or adding a new migration without a valid upgrade fails CI.

## Test plan

- Alembic graph/single-head and model-schema parity tests.
- Empty/current/legacy/behind/ahead/missing-version database cases on SQLite and PostgreSQL.
- Compose/pre-deploy success, failure, duplicate-launch, timeout, and app-start ordering.
- Disposable backup/rollback rehearsal for migration classes that support it.

## Done criteria

- [ ] The actual production platform and one migration owner are documented and checked in.
- [ ] Every deployment applies Alembic before new DB consumers become ready.
- [ ] Applications detect incompatible revisions without mutating schema.
- [ ] SQLite and PostgreSQL upgrade paths are tested from supported states.
- [ ] Backup, failure, expand-contract, and rollback procedures are rehearsed and current.

## STOP conditions

- Stop after the topology/test report if the production deployment configuration is external or unavailable; request its location/owner rather than inventing wiring.
- Stop before touching any non-disposable database without operator authorization, verified backup/PITR, and an approved runbook.
- Stop if migration history has multiple heads or an unknown production stamp; reconcile history and data state in a dedicated reviewed migration.

## Maintenance notes

Every schema PR must include an Alembic revision, previous-release upgrade test, deploy compatibility note, and revision-guard success. Application startup may verify revisions but must never become the migration owner.
