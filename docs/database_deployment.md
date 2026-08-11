# Database Deployment Guide

## Overview

The News Collector operates with two database profiles:

- **Development:** defaults to SQLite stored under `data/news.db`. This mode
  is optimized for local workflows and does not require any external
  services.
- **Production/Staging:** *intended* to promote the storage layer to
  PostgreSQL whenever `ENV`, `APP_ENV`, or `ENVIRONMENT` resolve to
  `production`, `prod`, `staging`, or `stage` — but see "PostgreSQL is not
  actually usable yet" below before relying on this.

The runtime environment is detected via `noticiencias/config_manager.py` and the
selected profile is exposed through `get_runtime_config().database_config`.

## Environment Variables

When PostgreSQL is enabled the following variables are read at process start
(using the `NOTICIENCIAS__` prefix):

| Variable                                    | Purpose                                   | Default                   |
| -------------------------------------------- | ------------------------------------------ | -------------------------- |
| `NOTICIENCIAS__DATABASE__HOST`              | PostgreSQL host                           | `localhost`               |
| `NOTICIENCIAS__DATABASE__PORT`              | PostgreSQL port                           | `5432`                    |
| `NOTICIENCIAS__DATABASE__NAME`              | Database name                             | `noticiencias`            |
| `NOTICIENCIAS__DATABASE__USER`              | Connection user                           | `collector`               |
| `NOTICIENCIAS__DATABASE__PASSWORD`          | Password for the user                     | empty string              |
| `NOTICIENCIAS__DATABASE__SSLMODE`           | Optional SSL mode (e.g., `require`)       | (leave blank for default) |
| `NOTICIENCIAS__DATABASE__CONNECT_TIMEOUT`   | Connect timeout in seconds                | `10`                      |
| `NOTICIENCIAS__DATABASE__STATEMENT_TIMEOUT` | Statement timeout in milliseconds         | `30000`                   |
| `NOTICIENCIAS__DATABASE__POOL_SIZE`         | Base pool size                            | `10`                      |
| `NOTICIENCIAS__DATABASE__MAX_OVERFLOW`      | Additional connections beyond the pool    | `5`                       |
| `NOTICIENCIAS__DATABASE__POOL_TIMEOUT`      | Seconds to wait for a pooled connection   | `30`                      |
| `NOTICIENCIAS__DATABASE__POOL_RECYCLE`      | Seconds before recycling idle connections | `1800`                    |

Ensure these variables are provided by the orchestrator (Docker, systemd,
Kubernetes secrets, etc.) before switching to the production profile.

## Schema authority: Alembic, not `create_all`

`DatabaseManager.__init__` (`news_collector/storage/database.py`) does exactly
two things on every process start:

1. Builds an SQLAlchemy engine with the pooling/timeout settings above.
2. Runs `Base.metadata.create_all(engine)`, which creates any table that is
   completely missing. **It never alters an existing table** — it will not
   add a column, retype one, or create an index on a table that's already
   there.

Alembic is the only thing that changes an existing table's shape. There is no
runtime schema-repair step; the historical `_run_schema_migrations()` method
this file used to call is dead, commented-out code — it does not run, and no
current migration doc or comment should imply otherwise.

- **Local/dev**: `make refinery` depends on `make migrate` (`Makefile:108`),
  so `alembic upgrade head` runs before the Streamlit app starts.
- **Manual/anywhere**: `python scripts/migrate.py up` (wraps
  `alembic upgrade head`) or `alembic upgrade head` directly.
- **Read-only check**: `python scripts/check_migration_revision.py` compares
  the configured database's `alembic_version` to the packaged head without
  writing anything — see `news_collector/storage/migration_guard.py`. Use
  this to detect drift; never wire it to auto-migrate (see below).

## PostgreSQL is not actually usable yet

While investigating plan 046 ("Prove and automate production database
migrations"), attempting to run a real disposable-PostgreSQL migration test
surfaced three independent, stacked gaps — each would have to be fixed before
any PostgreSQL deployment of this backend (production or otherwise) could
work at all:

1. **No PostgreSQL driver is installed.** `psycopg2` (or any other
   `postgresql` DBAPI) is absent from `pyproject.toml`, `requirements.txt`,
   and every `.lock` file. `DatabaseManager`/`alembic/env.py` build a
   `postgresql://` SQLAlchemy URL correctly, but `create_engine()` fails with
   `ModuleNotFoundError: No module named 'psycopg2'` the instant it's used —
   in the Docker image built from this repo, in CI, everywhere.
2. **`docker-compose.yml`'s `refinery` and `collector` services set the
   wrong environment variables.** They export `DATABASE_URL`,
   `DATABASE_DRIVER`, and `POSTGRES_HOST`/`USER`/`PASSWORD`/`PORT` — none of
   which `news_collector`/`noticiencias.config_manager` reads. The only
   recognized override prefix is `NOTICIENCIAS__DATABASE__*` (see
   `.env.example`). As shipped, these two compose services silently fall
   back to the SQLite default instead of talking to the `db` Postgres
   service, even though the compose file visually looks Postgres-configured.
3. **The committed `config.toml` hardcodes one developer's absolute local
   filesystem paths** (`[paths]` and `[logging].file_path`, all
   `/home/carlos/VS_Code_Projects/...`). Any container or CI runner that
   copies this file in — which the current `Dockerfile`/`.dockerignore`
   does — crashes on startup trying to `mkdir` a path that doesn't exist on
   that machine and it doesn't have permission to create.

None of these three are fixed here. Each is a real production/portability
defect in its own right, independent of plan 046 and larger than a
migrations plan should absorb as a side effect — item 1 alone is a new
pinned dependency across every hash-locked requirements file, which needs
its own review (new transitive CVEs, wheel availability, refinery/security
lock drift), not a one-line addition to make a test go green. Fixing a test
by loosening the boundary of what the fix touches is the wrong direction;
these are recorded here as their own follow-up, not folded into this plan.

**Practical consequence for this plan**: the "disposable PostgreSQL
migration test" in the Verification table below (`docker compose
--profile migration-test run --rm migration-test`) could not be built —
there is no working Postgres path to run it against yet. The SQLite-side
proof (every revision, downgrade roundtrips, model/schema parity, single
linear history) is real and green; the equivalent PostgreSQL proof is
blocked on the three gaps above, not attempted as a shortcut.

One more risk worth flagging for whoever fixes PostgreSQL support: revision
`2447e261ecf4` creates `uq_articles_content_hash` using
`sqlite_where=sa.text(...)`, a SQLite-dialect-specific partial-index
argument. Even once psycopg2 is installed, this line will likely need a
PostgreSQL-equivalent (`postgresql_where=...`) or it will silently create a
full (non-partial) index on Postgres instead of the intended partial one —
review this migration specifically when PostgreSQL is actually built out.

## Production deployment topology — not discoverable in this repository

Plan 046 ("Prove and automate production database migrations") requires
identifying the single accountable owner that runs `alembic upgrade head`
before a production deploy's new database consumers become ready. That
inventory was attempted and **could not be completed from this repository**:

- No Kubernetes manifests, `fly.toml`, `railway.json/toml`, `render.yaml`,
  `Procfile`, or other cloud-provider deployment configuration exists
  anywhere in the tracked tree.
- `.github/workflows/daily_collector.yml` runs the collector on an ephemeral
  GitHub Actions runner and commits a JSON export back to this repo — it does
  not deploy or touch a persistent production database.
- `.github/workflows/release.yml` builds a Docker image and attaches it to a
  GitHub Release as a downloadable artifact with manual `docker load`
  instructions. It never pushes to a registry and never deploys anywhere.
- `docker-compose.yml` and the `Dockerfile` describe how to run this stack
  locally (or on a host you provision by hand); neither is a hosted
  deployment target with an inferable identity, replica count, or scheduler.

**This is a genuine STOP condition, not an oversight to invent past.** Per
plan 046's own instructions: *"Stop after the topology/test report if the
production deployment configuration is external or unavailable; request its
location/owner rather than inventing wiring."* If a production deployment of
this backend exists, its configuration and migration-owning job live outside
this repository (a separate ops repo, a platform's dashboard-configured
pipeline, or a manual runbook someone runs by hand) — whoever owns that
deployment needs to point at it, or confirm no production deployment exists
yet. Until then, no doc here should claim a specific pipeline runs
`alembic upgrade head` before deploy, because none can be shown to.

## What can be verified today (disposable environments only)

Everything below is proven against ephemeral, disposable databases — never
against a shared or production instance:

- `tests/test_database_migrations.py`: every supported starting revision
  (including a fresh empty database) reaches head; head-upgrade is
  idempotent; model metadata matches the schema Alembic head produces;
  migration history is a single linear chain; downgrade/upgrade roundtrips
  for every revision whose `downgrade()` is complete enough to trust (see the
  in-file note on why `2447e261ecf4`'s downgrade is excluded — it is
  admittedly incomplete by its own comment, and rewriting a historical,
  already-applied migration file is out of scope for this pass).
- A disposable PostgreSQL migration test is **not yet possible** — see
  "PostgreSQL is not actually usable yet" above. Only the SQLite path is
  proven today.
- `python scripts/check_migration_revision.py`: read-only, reusable
  revision-guard CLI. Distinguishes up-to-date / behind / ahead-or-diverged /
  never-migrated / unreachable, and writes nothing in any of those cases.

## Concurrency, backups, and rollback (documented, not yet rehearsed)

These procedures are recorded here as the target process for whoever owns
the real production deployment; they have **not** been rehearsed against a
production-shaped database in this session, because doing so requires the
topology this document just said is unavailable.

1. **Preflight**: confirm current revision (`check_migration_revision.py`),
   confirm a recent backup/PITR checkpoint exists, review the migration for
   destructive operations (column/table drops, type narrowing).
2. **Expand/contract for anything destructive**: add new columns/tables
   first, deploy code that writes both old and new shapes, backfill, then
   drop the old shape in a later migration — never combine "add" and
   "remove" for the same concept in one revision if the app can't tolerate
   downtime.
3. **Apply**: exactly one process runs `alembic upgrade head` (or
   `scripts/migrate.py up`) to completion before any replica of
   collector/refinery starts against the new revision. If the deployment
   platform can launch duplicate release attempts concurrently, the
   migration job must use a lock (Postgres advisory lock, or the platform's
   own single-instance job primitive) — Alembic does not serialize
   concurrent `upgrade head` invocations on its own.
4. **Verify**: `check_migration_revision.py` reports `up_to_date` before
   traffic is routed to the new release.
5. **Rollback**: prefer a forward-fix migration over `alembic downgrade`.
   Downgrading in production requires an explicit, reviewed decision because
   most downgrades in this history are lossy (see `2447e261ecf4`'s
   incomplete downgrade above) — never run one against non-disposable data
   without a verified backup and operator sign-off.

## Development Reset

For local development you can safely delete `data/news.db` to start with a
clean slate. No additional services are required when `ENV=development` or
when the environment variables above are not provided.
