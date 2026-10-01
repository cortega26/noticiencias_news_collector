# ADR-0011: Local publication runs vs. the hosted webhook receiver (split state)

- **Date**: 2026-09-30 (decided 2026-09-30)
- **Status**: Accepted

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

**Chosen: the hosted serving instance is a durable inbox; the local node
pulls and replays (store-and-forward).** The system of record stays local
(where the collector, refinery and admin actually write); the hosted
receiver never needs the production database. Deliveries accumulate durably
on the hosted side (they already do: `webhook_receipts` persists the raw
payload with a deterministic `delivery_key`), and a local ops script pulls
them through the same handler the serving webhook uses — receipt-first and
idempotent, so replays are no-ops.

This inverts the sync direction: pulling works behind NAT, needs no tunnel,
no secret flipping, and tolerates the deploy arriving hours after the
publish session — the exact conditions that caused the 2671 incident.

Implementation spec: `spec-webhook-inbox-pull.md` (`GET
/v1/admin/webhook/receipts` + `scripts/ops/pull_webhook_receipts.py` +
`make webhooks-pull`). The 2671 manual replay remains the emergency path and
was the evidence this decision rests on.

If the product ever needs to operate without the operator's laptop, the
successor option is to move the system of record to the VM (single writer,
persistent volume, backups) and make local a client; that is a separate
strategic initiative, not a prerequisite for this decision.

## Consequences

Easier: local state converges to the truth without anyone remembering a
ritual — callbacks wait in the inbox until pulled; the raw payload is kept
for audit on the side that receives it; the same pull generalizes to every
frontend callback (`validation_result`, `publish_complete`) and future
report flows.

Harder / constrained: convergence is eventual (a publish's `publish_complete`
applies on the next pull, not exactly when the deploy finishes), so the admin
can briefly show `publishing` after the article is live; the puller must be
run (startup hook or timer) or state waits; the hosted inbox needs a
retention/prune policy before it grows without bound; and the hosted receipts'
processing status is meaningless across databases (the puller must consider
all statuses, since the hosted handler "processed" deliveries as no-ops).

Rejected, as before: session tunnels (deploy timing), manual replay only
(state lies), DB file sync (two writers), permanent local callback URL (the
reason the OCI cutover exists), hand-importing receipts (loses the real
delivery key).

## Alternatives considered

| Option | Reason rejected |
|--------|-----------------|
| Ignore the split; reconcile only when noticed | State silently diverges; the admin lies about in-flight publications |
| Sync/copy `news_v3.db` between local and OCI | Two writers on one SQLite file across machines — corruption and undefined ownership |
| Point the frontend callback at the local PC permanently | The OCI cutover exists precisely because callbacks must not depend on a local PC being on (`spec-oci-hosting-migration.md`) |
| Import the hosted receipt into the local DB after the fact | Reintroduces the same manual ritual as option 3 without using the real delivery key |
