# Database Deployment Guide

## Overview
The News Collector operates with two database profiles:

- **Development:** defaults to SQLite stored under `data/news.db`. This mode
  is optimized for local workflows and does not require any external
  services.
- **Production/Staging:** automatically promotes the storage layer to
  PostgreSQL whenever `ENV`, `APP_ENV`, or `ENVIRONMENT` resolve to
  `production`, `prod`, `staging`, or `stage`.

The runtime environment is detected via `config/settings.py` and the selected
profile is exposed through `config.DATABASE_CONFIG`.

## Environment Variables
When PostgreSQL is enabled the following variables are read at process start
(using the `NOTICIENCIAS__` prefix):

| Variable | Purpose | Default |
| --- | --- | --- |
| `NOTICIENCIAS__DATABASE__HOST` | PostgreSQL host | `localhost` |
| `NOTICIENCIAS__DATABASE__PORT` | PostgreSQL port | `5432` |
| `NOTICIENCIAS__DATABASE__NAME` | Database name | `noticiencias` |
| `NOTICIENCIAS__DATABASE__USER` | Connection user | `collector` |
| `NOTICIENCIAS__DATABASE__PASSWORD` | Password for the user | empty string |
| `NOTICIENCIAS__DATABASE__SSLMODE` | Optional SSL mode (e.g., `require`) | (leave blank for default) |
| `NOTICIENCIAS__DATABASE__CONNECT_TIMEOUT` | Connect timeout in seconds | `10` |
| `NOTICIENCIAS__DATABASE__STATEMENT_TIMEOUT` | Statement timeout in milliseconds | `30000` |
| `NOTICIENCIAS__DATABASE__POOL_SIZE` | Base pool size | `10` |
| `NOTICIENCIAS__DATABASE__MAX_OVERFLOW` | Additional connections beyond the pool | `5` |
| `NOTICIENCIAS__DATABASE__POOL_TIMEOUT` | Seconds to wait for a pooled connection | `30` |
| `NOTICIENCIAS__DATABASE__POOL_RECYCLE` | Seconds before recycling idle connections | `1800` |

Ensure these variables are provided by the orchestrator (Docker, systemd,
Kubernetes secrets, etc.) before switching to the production profile.

## Migration Procedure
The `DatabaseManager` performs the following actions on startup (this is the
runtime source of truth for schema safety):

1. Builds an SQLAlchemy engine with PostgreSQL-friendly pooling, timeouts,
   and statement timeout wiring.
2. Executes `Base.metadata.create_all` to provision missing tables.
3. Runs `_run_schema_migrations` which performs idempotent DDL fixes.

Alembic is available for **manual** or **production** migration workflows
(`scripts/migrate.py`), but it is not invoked at runtime. When you add
structural changes, keep Alembic revisions and `_run_schema_migrations`
aligned so dev (SQLite) and prod (Postgres) stay consistent.

For production changes follow this extended checklist:

1. **Prepare:**
   - Capture the current schema via `pg_dump --schema-only` (or SQLite
     equivalent during the initial migration).
   - Assess upcoming schema changes and confirm corresponding code updates.
2. **Dry Run:**
   - Start an instance against a staging database populated with sanitized
     production data.
   - Verify that `_run_schema_migrations` completes without errors and that
     the application boots cleanly.
3. **Apply:**
   - Deploy the new release.
   - Monitor application logs for the "Base de datos configurada"
     confirmation message.
4. **Verify:**
   - Run smoke tests (collector ingest and scoring) to ensure write
     throughput remains within expected ranges.
   - Inspect `pg_stat_activity` for queue depth and connection pool
     utilization.

## Replication and Backups
- **Replication:** configure streaming replication (or managed equivalents) on
  the PostgreSQL cluster. Ensure replicas are placed in separate zones and
  apply the same statement timeout parameters for consistent behavior.
- **Backups:** schedule nightly logical backups via `pg_dump` plus periodic
  physical snapshots. Store artifacts in encrypted object storage with a
  minimum 14-day retention policy.
- **Recovery Drills:** perform quarterly restore exercises into a temporary
  environment, replaying `_run_schema_migrations` afterwards to validate
  forward compatibility.

## Development Reset
For local development you can safely delete `data/news.db` to start with a
clean slate. No additional services are required when `ENV=development` or
when the environment variables above are not provided.
