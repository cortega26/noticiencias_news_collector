# Spec — webhook inbox pull (local system of record, hosted durable inbox)

## Context

ADR-0011 documents the split found while verifying article 2671: publication
runs execute against the local database, but the frontend's post-deploy
callback is delivered to the hosted serving instance
(`api.noticiencias.com`), which owns a different database. The hosted handler
processes the delivery against *its* DB (a no-op: no matching attempt), and the
local node never learns the outcome. Attempt 16 stayed `PR_CREATED` and the
article `publishing` until the exact delivery was replayed by hand through the
real webhook path (`id:v1:36785713548:publish_complete`).

The durable pieces already exist on both sides: `webhook_receipts` persists
each delivery's raw payload (hosted and local), `compute_delivery_key` is
deterministic, `handle_webhook_event` is receipt-first and idempotent, and
publication transitions are state-filtered. What is missing is a way to move
deliveries **from** the hosted inbox **toward** the local system of record —
a pull, not a push: the local machine is behind NAT, and deploys can land
hours after the publish session, so tunnels and secret-flipping are rejected
(ADR-0011).

## Goal

Make the hosted serving instance a durable **inbox** and let the local node
**pull and replay** deliveries through the real webhook path:

1. Hosted `GET /v1/admin/webhook/receipts` (admin-authenticated, read-only)
   returns recent receipts including the raw payload, oldest-last, with an
   `after_id` cursor and a bounded `limit` — no schema change.
2. `scripts/ops/pull_webhook_receipts.py` fetches receipts, parses each
   payload with the real contract, and applies it with `handle_webhook_event`
   against the local DB. Duplicates are skipped by the local receipt's
   delivery key; malformed payloads are reported, never guessed; a connection
   failure exits non-zero so a timer surfaces it.
3. Wiring/docs so the operation is routine: `make webhooks-pull`, an opt-in
   best-effort pull at `make admin` startup, and a runbook section with the
   systemd-timer alternative.

Non-goals: no hosted-side retention/prune in this change (documented
follow-up for the VM); no scheduler infrastructure in the repo (same
convention as `reconcile_publication_attempts.py`); no change of who owns the
system of record today (that is the strategic option in ADR-0011); no change
to the webhook push path.

## Architecture

### Storage — `news_collector/storage/webhook_receipt_repository.py`

Add `list_receipts(*, after_id: int | None = None, limit: int = 200) ->
list[WebhookReceiptView]`: all statuses (the hosted handler may have
"processed" a delivery as a no-op — status is meaningless across databases),
ordered by `id` ascending (a stable cursor), filtered by `id > after_id`.
Read-only; the puller pages forward until a short page.

### Contract — `news_collector/contracts/admin.py`

- `AdminWebhookReceipt`: `id`, `delivery_key`, `event_type`, `status`,
  `attempts`, `payload: Dict[str, Any]`, `received_at`, `processed_at`.
  `payload` is the frontend CI envelope (no secrets); admin-authenticated.
- `AdminWebhookReceiptEnvelope`: `receipts: List[AdminWebhookReceipt]`,
  `meta: Dict[str, Any]` (`count`, `latest_id`).

### Serving — `news_collector/serving/api.py`

`GET /v1/admin/webhook/receipts?after_id=&limit=`, `Depends(verify_admin_token)`,
`limit` 1..1000 (default 200). Read-only composition over the storage
repository (LAW-B4 allowed exception); no mutation, no processing.

### Ops — `scripts/ops/pull_webhook_receipts.py`

- Endpoint resolution: `--endpoint` → `BACKEND_ADMIN_URL +
  /v1/admin/webhook/receipts` → origin of `BACKEND_WEBHOOK_URL` (scheme+host;
  the webhook path is not part of the admin surface).
- Token: `--token` → `ADMIN_API_KEY`. Refuses to run without both.
- Pages with `after_id`, `--limit` per page (default 200) and a safety cap
  `--max-receipts` (default 2000).
- Each payload: `parse_webhook_payload` (invalid → `malformed` count, logged
  with the delivery key) then `handle_webhook_event(event, db)` — the same
  function the serving endpoint calls. Outcome counters: `replayed`,
  `duplicates`, `failed`, `malformed`.
- `--dry-run`: resolves and parses, checks the local receipt
  (`db.webhook_receipts.get_receipt`) but writes nothing.
- Exit 0 on a completed pass (malformed rows are a report, like the
  reconciler), 1 on an unexpected failure (auth/connection).

### Wiring

- `Makefile`: `webhooks-pull` target.
- `scripts/dev/admin_stack.sh`: when `WEBHOOK_INBOX_PULL=1|true|yes` and an
  endpoint is resolvable, run one best-effort pull before starting the stack
  (short timeout, never fatal). Default off; documented in the header.
- Docs: `docs/RUNBOOK_LOCAL_DEV.md` (usage + timer), `docs/PIPELINE_CONTRACTS.md`
  (admin surface bullet), `docs/PRODUCT_FLOW.md` (acknowledgment path),
  ADR-0011 updated to **Accepted** with this decision recorded in place.

## Acceptance

1. Receipts survive a "hosted processed as no-op" delivery: the endpoint
   returns it with its raw payload regardless of status; `after_id`/`limit`
   behave deterministically (id order).
2. Replaying the 2671 shape through the puller against a DB with the local
   attempt in `PR_CREATED` completes it exactly like the serving webhook
   (attempt `COMPLETED`, article `completed`, `published_at`/`published_url`
   set, `publication_events.deployed`), and a second run is a duplicate no-op.
3. Malformed payloads are counted and logged, never applied; `--dry-run`
   writes nothing; a connection error exits 1.
4. Endpoint auth mirrors the admin surface (401/403 without a valid key,
   fail-open only in the explicit development tier).

## Verification

- Unit: `tests/unit/storage/test_webhook_receipt_repository.py` (list
  ordering/filter/limit), `tests/unit/ops/test_pull_webhook_receipts.py`
  (paging, replay, duplicates, malformed, dry-run, failure exit),
  `tests/test_serving_admin_api.py` (endpoint auth + shape + cursor).
- `make lint && make type && make test`,
  `make test-contracts && make test-boundaries`, `make admin-contracts-check`,
  `make docs-check`, `make inventory-refresh && make inventory-check`.
- Manual: point the puller at the real hosted inbox with a dry-run, then a
  real run; verify the local summary and the absence of duplicate effects.

## Risks / notes

- Delivery keys make replay safe; the puller must never synthesize payloads.
- Receipt `payload` is exposed to admin-authenticated readers only; it holds
  CI envelope fields (repo, sha, diagnostics), no credentials.
- The puller's safety cap means a very stale local DB may need two runs
  (`--after-id` allows explicit paging when desired).
- Hosted receipt retention is unbounded today; a prune policy (e.g. keep 30
  days) is a follow-up for the VM before the inbox grows.
