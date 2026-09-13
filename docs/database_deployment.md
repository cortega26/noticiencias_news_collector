# SQLite deployment and migrations

Status: Active. Repository configuration checked 2026-09-04.

SQLite is the selected development and production database (operator decision
recorded with rejected Plan 046). PostgreSQL-related settings, dependencies
and legacy Compose services are not a supported production deployment recipe.
Do not infer a PostgreSQL migration roadmap from their presence.

## Configuration authority

`noticiencias/config_manager.py` resolves built-in defaults, `config.toml`,
repo-root `.env` and process environment. `news_collector/config/settings.py`
exposes the runtime facade. The committed database path is `data/news_v3.db`;
overrides may select another file. Confirm the effective path before any
inspection, backup or migration. `docs/config_fields.md` documents schema
defaults, which can differ from values committed in `config.toml`.

## Schema ownership

`news_collector/storage/database.py` creates missing tables through SQLAlchemy
metadata, but that does not upgrade existing table definitions. Alembic
revisions under `alembic/` own schema evolution.

From the backend repository with its bootstrapped environment:

```bash
.venv/bin/python scripts/check_migration_revision.py
make migrate
.venv/bin/python scripts/check_migration_revision.py
```

The revision checker reads migration state without applying migrations.
`make migrate` applies them to the configured database. `make refinery`
invokes migrations before the legacy UI; `make admin` and `make serve` do not
have that Make prerequisite, so migrate explicitly during setup/deployment.

`tests/test_database_migrations.py` covers disposable SQLite upgrades,
idempotence, model/schema parity and supported downgrade roundtrips. Its
exceptions for historical incomplete downgrades are not production rollback
instructions.

## Hosted configuration and limits

`Dockerfile.serving`, `fly-serving.toml` and `fly-tunnel.toml` describe a
hosted serving/tunnel arrangement. Their existence supersedes old reports
that no hosted configuration exists. The serving image starts uvicorn; these
files do not declare an Alembic release step or a persistent database volume.
They therefore do not establish shared, durable publication state with the
collector's database. Verify the effective database, persistence and migration
owner in the actual deployment before relying on remote callbacks.

The older `docker-compose.yml` includes PostgreSQL and Streamlit services;
it is legacy scaffolding, not a production-parity or current Astro admin stack.
No live deployment, backup or restoration was verified by this documentation audit.

## Operational procedure

1. Identify the configured SQLite file, its owner process and current revision.
   Preserve a consistent SQLite backup, including committed WAL state; a raw
   copy of only the main file while writers are active is not a restore proof.
   See [SQLite WAL documentation](https://www.sqlite.org/wal.html#the_wal_file).
2. Stop or drain relevant writers before a migration maintenance window.
   Assign one migration owner; do not run concurrent Alembic upgrades.
3. Apply the reviewed migration, then confirm the revision before starting
   consumers. Keep a record of the release and backup used.
4. Prefer a forward repair for migration failures. A downgrade can lose data;
   review its implementation and test recovery against a disposable restored
   copy before applying it to an operational database.
5. Rehearse backup restoration and health checks in isolation. Record timing,
   revision and integrity results before stating recovery guarantees.

For a fresh development database, configure a new disposable SQLite path and
migrate it. Do not delete the default database as a routine reset: it may hold
editorial work or publication identity evidence.
