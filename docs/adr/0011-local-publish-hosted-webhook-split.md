# ADR-0011: Local publication runs vs. the hosted webhook receiver (split state)

- **Date**: 2026-09-30
- **Status**: Proposed

## Context

The serving layer (webhook + admin API) runs **hosted** at
`api.noticiencias.com` (OCI VM, cutover from Fly on 2026-09-26, see
`spec-oci-hosting-migration.md`). It owns its own database.

Publication runs, however, are triggered from the **local** admin GUI
(`make admin` → local uvicorn `:8000` → local `data/news_v3.db`). The two
databases are not shared.

The frontend's post-deploy callback
(`.github/workflows/deploy.yml` → `scripts/post-publish-callback.js`) sends
`publish_complete` with a `deploy_url` and the changed posts' `refinery_id`
values to a single `BACKEND_WEBHOOK_URL` repository secret — the hosted
backend. That is the **only** place `published_at` / `published_url` are set
(`apply_publish_complete` → `db.complete_publication_attempts`), and the only
path that transitions a publication attempt `PR_CREATED → COMPLETED`.

Split consequence, observed live: article 2671 was published by run 61 (PR
frontend #231 merged, Pages deploy green, article live at
`https://noticiencias.com/ciencia/2026-09-25-.../`), but the local DB kept the
article `publishing` and attempt 16 `PR_CREATED` forever, because the
acknowledgment landed in the hosted DB, which has no matching attempt. The
local admin keeps showing in-flight state that no longer exists.

The lost callback was replayed locally through the real webhook path on
2026-09-30 (`delivery_key id:v1:36785713548:publish_complete`, attempt 16 →
`COMPLETED`, `publication_events.deployed`), which proves the repair path but
does not remove the split.

## Decision

Not yet made — this ADR documents the gap and the options so the operator can
choose. Interim practice (used for 2671): when a local publish's
acknowledgment is lost to the hosted backend, replay the exact delivery into
the local backend via `handle_webhook_event` (receipt-first, idempotent by
delivery key) — never a manual UPDATE.

Recommendation:

1. **Target — operate from the backend that receives callbacks.** Run the
   admin/publish flow against the hosted service with a persistent, backed-up
   database (the OCI spec's SQLite is on the VM; a volume/backup story is
   required). One writer, one state, no replay.
2. **Near-term — route callbacks to the backend in use.** During local publish
   sessions, point `BACKEND_WEBHOOK_URL` at the local backend through an
   on-demand Cloudflare tunnel (the connector retired by the OCI cutover),
   restoring the hosted URL afterwards. Small operational cost, no code change.
3. **Stopgap — scripted post-session reconcile.** Keep local-first operation and
   formalize the manual replay (a small ops script/runbook) for every publish
   session. Acceptable only as a temporary measure.

## Consequences

Easier with 1 (recommended): publication state is truthful wherever the
operator looks; receipts, reports and admin reads share one database; no
per-session ritual.

Harder / constraints: the hosted DB needs durability, backups and access
control; the hosted admin surface needs the operator's credentials; migrating
the operating DB to the VM must not fork `data/news_v3.db` further.

With 2: no data migration, but every publish session depends on a tunnel being
up, and forgetting to restore the secret silently recreates the split.

With 3: zero infra change, but state stays wrong until someone replays, and
each local publish leaves hosted receipts with no local counterpart.

## Alternatives considered

| Option | Reason rejected |
|--------|-----------------|
| Ignore the split; reconcile only when noticed | State silently diverges; the admin lies about in-flight publications |
| Sync/copy `news_v3.db` between local and OCI | Two writers on one SQLite file across machines — corruption and undefined ownership |
| Point the frontend callback at the local PC permanently | The OCI cutover exists precisely because callbacks must not depend on a local PC being on (`spec-oci-hosting-migration.md`) |
| Import the hosted receipt into the local DB after the fact | Reintroduces the same manual ritual as option 3 without using the real delivery key |
