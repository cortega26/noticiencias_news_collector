# Plan 046: Prove and automate production database migrations — spec

## Outcome: REJECTED (operator decision 2026-08-11 — SQLite-only, no PostgreSQL)

> **Operator decision (2026-08-11):** "De momento no, si podemos alcanzar las
> mismas funcionalidades con sqlite así se hará." — PostgreSQL is not in the
> roadmap; SQLite stays the production database for as long as it covers the
> required functionality. The remaining PostgreSQL-specific scope of this
> plan (driver dependency, compose env-var fix, `config.toml` portability,
> disposable-Postgres migration test, production pre-deploy job) is
> explicitly **not** to be pursued. Do not re-audit as new work.

## What was delivered before the rejection (stays on main)

Everything this plan shipped that is SQLite-safe and deployment-independent
remains valid and tested: Alembic-first SQLite test coverage (18 tests),
the read-only migration revision guard (`migration_guard.py` +
`scripts/check_migration_revision.py`), and the doc corrections. These are
the durable value of the plan and are unaffected by the rejection.

## Original outcome record (PARTIAL — STOP conditions hit)

This plan's own STOP conditions are worded as instructions to follow, not
obstacles to route around:

> Stop after the topology/test report if the production deployment
> configuration is external or unavailable; request its location/owner
> rather than inventing wiring.

That condition is met (see "Step 1 finding" below), and a second,
unanticipated blocker was found empirically while trying to build the
PostgreSQL half of Step 2/6 (see "PostgreSQL is not usable yet" below). Both
are STOP conditions in spirit even though only the first is named in the
plan text: proceeding past either would mean inventing wiring or a
capability this repository doesn't actually have.

## What was in scope for this pass

Per the plan's Steps 2, 3, and part of 5 — everything that is provable
without a real production deployment or a working PostgreSQL path:

1. **Step 2 (Alembic as schema authority in tests)** — done for SQLite.
2. **Step 3 (read-only application revision guard)** — done, fully tested.
3. **Step 5 (correct stale docs/scripts)** — done.
4. Step 1 (identify production owner) — investigated, reported as
   undiscoverable (STOP).
5. Step 2/4/6's PostgreSQL-specific halves — attempted, found blocked on
   three independent pre-existing gaps (STOP; see below).

## Goals actually achieved

1. **Alembic-first test coverage** (`tests/test_database_migrations.py`,
   now 18 tests, up from 7):
   - Every one of the 5 supported starting revisions reaches head.
   - Head-upgrade is idempotent (pre-existing test, kept).
   - Downgrade → re-upgrade roundtrip for every revision whose `downgrade()`
     is complete enough to trust (`a3f1b2c4d5e6`, `a54ba7f7dabb`,
     `b61c2d3e4f50`). `2447e261ecf4` is excluded — its own code comment
     admits the downgrade is incomplete ("omitting exhaustive list for
     brevity"); rewriting a historical, already-shipped migration file is
     out of scope for this pass, so it's flagged instead of silently
     trusted.
   - Model metadata vs. Alembic-head schema parity check — this is the
     "delete a migration op / add an un-migrated model column → suite
     fails" case the plan's Step 2 Verify clause asks for.
   - Migration history is a single, fully linear chain (no branch points).

2. **Read-only revision guard** (`news_collector/storage/migration_guard.py`
   + `scripts/check_migration_revision.py`, 6 tests in
   `tests/unit/storage/test_migration_guard.py`):
   - Distinguishes `up_to_date` / `behind` / `ahead-or-diverged` /
     `missing_version_table` / `unreachable`, each with a distinct,
     credential-free diagnostic message.
   - Never mutates schema in any branch — verified directly (tests assert
     the table set is unchanged after every check, including on a
     completely fresh, empty SQLite file).
   - Deliberately does **not** go through `DatabaseManager` to get its
     engine, because that class's constructor runs
     `Base.metadata.create_all()` — which would silently create tables on
     the very schema this guard exists to check untouched. It builds its
     own bare engine via a new shared `build_database_url()` helper
     extracted from `DatabaseManager._setup_database` (pure URL
     construction, no side effects, used by both call sites so they can't
     silently point at different databases).

3. **Corrected stale documentation/comments** (Step 5):
   - `news_collector/storage/database.py`'s class docstring no longer
     claims `_run_schema_migrations()` runs — that method is dead,
     commented-out code, and the docstring now says so plainly.
   - `scripts/migrate.py`'s comment no longer references the same dead
     method.
   - `docs/database_deployment.md` — full rewrite. The old version
     contradicted itself in the same section (called `create_all` "the
     runtime source of truth for schema safety" while also calling Alembic
     the "only" source of truth), referenced `_run_schema_migrations` as if
     live in the Recovery Drills section, and had a garbled/corrupted
     checklist line (`"Capture the current schema via pg_dump --schema-only
     - [x] Check and update equivalent documentation <!-- id: 2
     -->migration)."`). The new version states one consistent story: Alembic
     owns schema changes, `create_all` only creates missing tables, and
     documents both STOP-condition findings below directly instead of
     assuming they're solved.

## Step 1 finding: production deployment topology is not discoverable

A full recon (this session, plus an independent Explore subagent pass) found
no Kubernetes manifests, `fly.toml`, `railway.json/toml`, `render.yaml`,
`Procfile`, or any other cloud-provider deployment configuration anywhere in
the tracked tree. `.github/workflows/daily_collector.yml` only commits a
JSON export back to the repo from an ephemeral runner; `release.yml` only
packages a downloadable Docker image artifact and never deploys it anywhere.
`docker-compose.yml`/`Dockerfile` describe a local/self-hosted run, not a
named, ownable deployment target.

Per the plan's own STOP instruction, this is reported rather than invented:
**if a production deployment of this backend exists, its owner needs to
point at it** (a separate ops repo, a platform dashboard, or a manual
runbook) — nothing in this repository can currently name it. Full detail:
`docs/database_deployment.md` § "Production deployment topology — not
discoverable in this repository".

**Update (2026-07-22, operator-confirmed)**: asked directly — no production
deployment of this backend exists yet. This confirms the STOP finding above
rather than changing it: there is still nothing to point Steps 2/4/6's
PostgreSQL-specific work at, and the second STOP below (PostgreSQL isn't
usable yet regardless of deployment topology) remains independently true.
046 stays PARTIAL; this is not a gap in the prior pass, it's the STOP
condition operating exactly as designed. Revisit once a production
deployment is stood up.

## Second, empirically-discovered STOP: PostgreSQL is not usable yet

Plan 046 asks for a disposable PostgreSQL migration test
(`docker compose --profile migration-test run --rm migration-test` was the
planned command). Building it surfaced three independent, stacked defects,
each necessary to fix before *any* PostgreSQL deployment of this backend —
production or otherwise — could work:

1. No `psycopg2` (or any PostgreSQL DBAPI) is declared in `pyproject.toml`,
   `requirements.txt`, or any `.lock` file. `create_engine()` fails
   immediately with `ModuleNotFoundError`.
2. `docker-compose.yml`'s `refinery`/`collector` services set
   `DATABASE_URL`/`DATABASE_DRIVER`/`POSTGRES_HOST` etc. — none of which
   `news_collector`/`noticiencias.config_manager` reads (only
   `NOTICIENCIAS__DATABASE__*` is recognized). Those two services silently
   fall back to SQLite today.
3. The committed `config.toml` hardcodes one developer's absolute local
   filesystem paths (`[paths]`, `[logging].file_path`), which crashes any
   container or CI runner that copies it in.

All three were reproduced empirically (see session transcript / commit
history around this plan), not inferred. None are fixed here — item 1 alone
is a new pinned dependency across every hash-locked requirements file
(`requirements.lock`, `requirements-refinery.lock`,
`requirements-security.lock`), which needs its own review (new transitive
CVEs, wheel availability, lock drift) rather than a one-line addition to
force a test green. Per the same discipline already applied to leaving
`config.toml` untouched (Step 3's guard build deliberately worked around it
via env vars instead of editing it), **making a test pass is not a license
to fix production code outside a plan's declared scope** — this is recorded
as its own follow-up in `docs/database_deployment.md` § "PostgreSQL is not
actually usable yet", including a fourth, smaller risk noticed in passing
(`2447e261ecf4`'s `sqlite_where` partial index is SQLite-dialect-specific
and will need a `postgresql_where` equivalent once Postgres actually works).

No `docker-compose.yml` changes are shipped by this plan — they were
prototyped, proven necessary but insufficient (blocked on the missing
driver), and reverted rather than left in an unverifiable, half-working
state that would misleadingly read as "Postgres support."

## Out of scope for this pass (left for a dedicated follow-up)

- Adding a PostgreSQL driver dependency and regenerating hash-pinned
  lockfiles (item 1 above).
- Fixing `docker-compose.yml`'s dead `refinery`/`collector` Postgres env
  vars (item 2 above) — the correct fix is known (rename to
  `NOTICIENCIAS__DATABASE__*`) but shipping it alone, without item 1, would
  still not produce a working, provable PostgreSQL path.
- Rewriting `config.toml`'s hardcoded absolute paths (item 3) — a portability
  bug independent of this plan, live in the user's tracked working config.
- Rewriting `2447e261ecf4`'s incomplete `downgrade()` — a historical,
  already-applied migration; out of scope to edit without dedicated review.
- Step 4's actual production pre-deploy job and Step 6's CI wiring for it —
  both require the topology from Step 1, which doesn't exist yet.
- Step 5's "rehearse on a disposable production-shaped database from the
  previous release" — requires both the topology (Step 1) and a working
  PostgreSQL path (blocked, see above).

## Verification

- `pytest tests/test_database_migrations.py -q` → 18 passed.
- `pytest tests/unit/storage/test_migration_guard.py -q` → 6 passed.
- `pytest --ignore=tests/e2e_pipeline -q` → 1165 passed, 13 failed (byte-for-byte
  the same 13 pre-existing failures as the `main` baseline, confirmed via
  `git stash`/`git stash pop` A-B comparison), 4 skipped.
- `make lint` → 1 pre-existing failure (`news_collector/serving/__main__.py`
  S104), confirmed identical on baseline via the same stash comparison.
- `make type` (`make typecheck`) → 3 pre-existing errors
  (`contracts/webhook.py` ×2, `collectors/dispatcher.py` ×1), confirmed
  identical on baseline.
- `make test-contracts` → 47 passed, coverage 77.56% (pre-existing gate
  failure, confirmed identical on baseline — not caused or worsened by this
  plan).
- `python scripts/check_migration_revision.py` manually exercised against a
  fresh dev SQLite DB during development; behaves as documented.
