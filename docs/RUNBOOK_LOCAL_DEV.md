# Local development runbook

Status: Active. Subordinate to `docs/SOURCE_OF_TRUTH.md`.

The product has sibling repositories `noticiencias_news_collector` (Python
backend and Astro admin) and `noticiencias` (public Astro site). Use Python
3.13+ and Node 24.x as declared in the repositories; apply the frontend
`.nvmrc` with `nvm use` when using nvm.

## Backend setup

Start in the backend repository. Preserve an existing `.env`:

```bash
make bootstrap
test -f .env || cp .env.example .env
make config-validate
make migrate
npm --prefix apps/admin ci
```

Runtime configuration comes from built-in defaults, `config.toml`, root
`.env`, then process environment. `apps/refinery/.env` is ignored legacy
configuration. Check `docs/config_fields.md` and `.env.example` for supported
keys. API keys, GitHub access and provider availability are needed only for
features that use them; do not assume a blank template provides full publication.

For configured Ollama models, a successful `/api/tags` request is insufficient:
the provider preflight also probes generation, which requires enough RAM.
The `NOTICIENCIAS__OLLAMA__API_URL`, `NOTICIENCIAS__OLLAMA__MODEL` and
`NOTICIENCIAS__GEMINI__API_KEY` overrides select those provider settings.

## Admin and public site

From the backend root:

```bash
make admin
```

This launches FastAPI at `http://localhost:8000` and the current Astro admin
at `http://localhost:4321`. One Ctrl+C stops the stack it started. If a
default port is busy, the stack bumps to the next free one (API `8000→…`,
GUI `4321→…`) and points the GUI proxy at the chosen API port, so a
leftover `make serve` never blocks `make admin`. Pin ports explicitly when
you mean it — `API_PORT=9000 make admin` dies instead of running elsewhere
if 9000 is taken. Split operation uses `make serve` and `make admin-dev`
in separate terminals (both accept the same `API_PORT=`/`GUI_PORT=`
overrides; `ADMIN_API_TARGET=` overrides the GUI proxy target).
Migrate before starting: these targets do not depend on `make migrate`.

When publishing from the desk, start the stack with `SERVING_RELOAD=0`
(e.g. `SERVING_RELOAD=0 make admin`): a publication run executes inside the
API process for ~12 min, and with the default auto-reload any source edit
restarts the API and kills the run (leaving a stale `running` row until the
lease recovers). Restart the stack manually after code changes in that mode.

Admin authentication and dev bypass are defined by `apps/admin/src/lib/api.ts`
and the serving auth code. The client uses localStorage with a build-time
`PUBLIC_ADMIN_API_KEY` fallback. A `PUBLIC_*` value is client-visible, so
it is not a server-side secret; see [Astro environment variables](https://docs.astro.build/en/guides/environment-variables/). Production serving requires `ADMIN_API_KEY`;
configure CORS through `ADMIN_CORS_ORIGINS` when using cross-origin requests.

In a separate terminal, start from the backend root and enter its sibling:

```bash
cd ../noticiencias
test -f .env || cp .env.example .env
npm ci
npm run dev -- --port 4322
```

Port 4322 avoids colliding with the admin at 4321. The public site's committed
image mode is `github`, selected in `data/image-delivery-mode.json` through
`src/utils/image-delivery-mode.js`. Mode and credentials together control R2
behavior. A production build can generate image artifacts and, in R2 mode
with credentials, upload derivatives.

`make refinery` remains the legacy Streamlit fallback at port 8501. It
bootstraps `.venv-refinery` and migrates before launching. Use it for legacy
compatibility work; it is not the default admin entrypoint.

## Collector entrypoints and dry-run limits

Run these from the backend root using `.venv/bin/python`:

| Command | Purpose |
| --- | --- |
| `scripts/run_collector.py --dry-run` | Exercise collection without the normal article-persistence path |
| `scripts/run_collector.py` | Run a full collection cycle |
| `scripts/run_collector.py --fast` | Run with the CLI's fast-processing option |
| `scripts/run_collector.py --sources nature mit_news` | Restrict collection to selected source IDs |
| `scripts/run_collector_continuous.py` | Repeated subprocess-based collection |
| `scripts/run_collector.py --healthcheck` | Check database, backlog and ingest recency |

Dry-run still initializes the system and can perform network/provider
preflight, logging and cache activity. An explicit `--export-json` writes an
export artifact even during dry-run. It is not an offline test, a read-only
sandbox, or evidence that queued articles were processed. Use fixture tests
for deterministic checks without external providers. See CLI `--help` for
exact options; the legacy root `main.py` entrypoint was removed.

## Validation

Backend Python changes start with `make lint`, `make type` and `make test`.
Add contract/boundary/publication checks according to `docs/AGENTS.md`'s
change matrix. `make type` includes its own test/coverage pass; its mypy
scope is the small target list in `Makefile`, not the whole package.

Admin changes also use `make admin-build` and `make admin-test`. Frontend
changes follow the sibling `AGENTS.md`: baseline `npm run lint` and
`npm run validate:content`, plus build, dist and unit tests for runtime/UI
changes and manual 375px/1280px checks for visual or interaction changes.
Cross-repo contract changes require both sides and strict schema parity.
See `docs/ci.md` for what aggregate commands include and omit.

## Troubleshooting and hosted configuration

For a SQLite lock, identify the exact owner process and stop it gracefully;
do not terminate every matching collector or start additional workers to
clear the symptom. For missing modules, rerun the appropriate bootstrap.
For schema errors, inspect content validation or database revision as appropriate.

See [database_deployment.md](database_deployment.md) for SQLite and migration
ownership, [runbook.md](runbook.md) for incidents, and [faq.md](faq.md) for
configuration errors.

### Webhook callbacks (hosted inbox → local pull)

Frontend CI callbacks (`validation_result`, `publish_complete`) are delivered
to the hosted serving instance (`api.noticiencias.com`), which persists each
delivery as a durable receipt before processing it. That instance is only an
**inbox**: publications and the admin operate against the local database, so
pending deliveries must be replayed into it:

```bash
make webhooks-pull                          # needs BACKEND_ADMIN_URL (or BACKEND_WEBHOOK_URL) + ADMIN_API_KEY
make webhooks-pull ARGS="--dry-run"         # report only, no writes
```

Replays go through the same handler as the serving webhook and are idempotent
by delivery key, so running the pull twice is safe. `make admin` can pull once
at startup with `WEBHOOK_INBOX_PULL=1`. The unattended option is a systemd
timer (e.g. every 15 minutes) running
`scripts/ops/pull_webhook_receipts.py`. See ADR-0011 and
`spec-webhook-inbox-pull.md`.

The local cursor only confirms that hosted rows were durably staged. The
puller retains unprocessed payloads, retries expired leases, and applies IDs in
order; it stops behind the first failed receipt. Exit 1 means an apply or fetch
failure needs another run and inspection; exit 2 means the cap, an active
lease, or other pending work remains. Do not treat an exit 0 from `--dry-run`
as an acknowledgment: that mode parses and reports without applying events.
The staging tables are additive Alembic migration `c6d1a4e8f203`.

Hosted serving configuration lives in `Dockerfile.serving` +
`docker-compose.serving.yml` (OCI VM systemd service `noticiencias-serving` —
see `spec-oci-hosting-migration.md`); `fly-serving.toml` / `fly-tunnel.toml`
are the retired Fly fallback kept for rollback. Repository files do not prove
the deployment is currently healthy or that it shares the collector database;
confirm the tunnel route and secrets in the deployment environment before
changing them.

The PostgreSQL/Streamlit `docker-compose.yml` is legacy scaffolding; it is
not a supported production-parity setup or the current admin stack.
