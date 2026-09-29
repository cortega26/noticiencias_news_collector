# Plan 060 / Phase 5a — Durable webhook receipts

> **Executor instructions**: Follow this spec step by step. Run every
> verification command and confirm the expected result before moving on. If a
> STOP condition triggers, stop and report — do not improvise. When done,
> annotate `plans/060/todo.md` Phase 5's first two checkboxes (partial: 5a
> done, reconciler/dashboard pending), update `docs/PIPELINE_CONTRACTS.md` and
> validate the plans ledger.
>
> **Drift check (run first)**:
> `git diff --stat 8dd3981..HEAD -- news_collector/contracts/webhook.py news_collector/serving/webhook_handler.py news_collector/serving/api.py news_collector/storage/models.py news_collector/storage/database.py tests/test_webhook.py tests/integration/test_publication_callback_contract.py docs/PIPELINE_CONTRACTS.md`
> On any in-scope drift, re-verify the "Current state" references; on a
> mismatch treat it as a STOP.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MED (additive table + best-effort handler; wire behavior unchanged)
- **Depends on**: Phase 3a/3c (lifecycle tables + dual-write), Phase 4c
  (publication workflow). First slice of Phase 5; reconciler (5b) and
  dashboard evidence (5c) follow.
- **Category**: reliability (plan 060 critical path)
- **Planned at**: backend `8dd3981`, 2026-09-25

## Why this phase exists

Plan 060 Phase 5 item 2 and the API decisions section:

> Backend authenticates/validates, persists the receipt, then processes it.
> Duplicate delivery returns the stored result without reapplying transitions.
> Webhook receipt returns `202` after durable receipt. … A processing failure
> remains visible as `failed/pending_retry` on the receipt instead of being
> discarded behind a successful response.

Today the endpoint parses the payload, processes inline, and always returns
202 with `{"accepted": true}`. A crash after the frontend's bounded retries
loses the callback forever; a replay re-runs the handler (safe only because the
underlying transitions happen to be state-filtered); a processing exception is
a log line and nothing else. There is no durable record that a delivery ever
arrived.

This slice makes the delivery itself durable and idempotent:

1. an optional `delivery_id` contract field (forward-compatible with the
   frontend sender) plus a deterministic derived key, so dedup works today
   without a frontend change;
2. a `webhook_receipts` table and typed repository;
3. receipt-first handling: persist → process → mark, with `processed` result
   replay, `failed` retention (error + attempts), and `received` recovery.

## Current state (verified at `8dd3981`)

- `contracts/webhook.py:31-92` — `FrontendWebhookEvent` (no delivery id) +
  `parse_webhook_payload`.
- `serving/webhook_handler.py` — `process_validation_result:26` (rejects on
  fail via `db.reject_publication_attempts`), `process_publish_complete:77`
  (completes via `db.complete_publication_attempts`), `_extract_deploy_url:125`.
  Both transitions are already idempotent/state-filtered
  (`article_repository.py:334,406`).
- `serving/api.py:1113-1165` — `POST /api/v1/webhook/frontend`, 202 always,
  invalid payload → 422, processing exception → logged and swallowed.
- `storage/models.py:864` — `PublicationEvent` exists but nothing writes it
  (separate Phase 5b work: per-attempt event log).
- `storage/database.py:177` — repositories exposed on `DatabaseManager`
  (`articles`, `sources`, `analytics`, `lifecycle`); `get_session()` commits on
  clean exit, rolls back and re-raises on exception (`:284-311`).
- Alembic head `e3f168a66d38`; head pinned in
  `tests/unit/storage/test_migration_guard.py:21`, revision lists in
  `tests/test_database_migrations.py:264,269`.
- Baselines: `pytest tests/test_webhook.py tests/integration/test_publication_callback_contract.py tests/unit/storage tests/unit/contracts/test_webhook_contract.py --no-cov -q` (record the count at Step 0).

## Scope

**In scope**:

- `news_collector/contracts/webhook.py` — optional `delivery_id` field +
  validator; `extract_deploy_url(event)`; `compute_delivery_key(event)`.
- `news_collector/storage/models.py` — `WebhookReceipt` model + status tuple.
- NEW `alembic/versions/<rev>_add_webhook_receipts.py` (down_revision
  `e3f168a66d38`, idempotent, complete downgrade).
- NEW `news_collector/storage/webhook_receipt_repository.py` +
  `db.webhook_receipts` exposure.
- `news_collector/serving/webhook_handler.py` — `handle_webhook_event`
  receipt-first orchestration; `process_*` return typed result dicts.
- `news_collector/serving/api.py` — endpoint delegates to
  `handle_webhook_event`; 202/422 semantics unchanged.
- Tests: new repository + handler integration tests; extend webhook contract
  and endpoint tests; migration revision lists + guard head.
- `docs/PIPELINE_CONTRACTS.md` webhook paragraph; `plans/060/todo.md`.

**Out of scope**:

- Frontend sender changes (the `delivery_id` field is optional; the frontend
  adopts it later), bounded frontend retries/diagnostics.
- `publication_events` per-attempt logging (5b) and the stale-attempt
  reconciler (5b) — do NOT write `publication_events` here.
- Dashboard health (5c), `serving/api.py` admin surfaces.
- Changing `reject`/`complete` transition semantics or the deploy-url-less
  completion behavior (a separate decision).

## Design

### Receipt key

`compute_delivery_key(event)`: `f"id:{delivery_id}"` when present; otherwise a
sha256 over the stable identity fields only — `event`, `commit_sha`, `branch`,
`status`, sorted `publication_ids`, `extract_deploy_url(event)` — so a rebuilt
retry (new timestamp) dedupes while genuinely different events don't.

### Table `webhook_receipts`

| column | type | notes |
|---|---|---|
| id | int PK | |
| delivery_key | String(200) | unique index `uq_webhook_receipts_delivery_key` |
| event_type | String(50) | |
| payload | JSON | `model_dump(mode="json", by_alias=True)` |
| status | String(20) | CHECK `received\|processed\|failed`, default `received` |
| attempts | int | default 0, incremented per processing attempt |
| result | JSON | processed outcome (`{"action": ..., "updated": n}`) |
| error | Text | last failure (`TypeError: ...`) |
| received_at | DateTime(tz) | default utcnow |
| processed_at | DateTime(tz) | set on processed/failed |

Index `ix_webhook_receipts_status_received_at` for the future reconciler.

### Repository (`db.webhook_receipts`)

Frozen `WebhookReceiptView`; methods `record_receipt(...) -> (view, created)`
(existing row wins; IntegrityError race falls back to the stored row),
`mark_processing(key) -> bool` (attempts += 1), `mark_processed(key, result)`,
`mark_failed(key, error)`, `get_receipt(key)`. Never raises for a missing key —
returns False/None like `LifecycleRepository`'s CAS.

### Handler

`handle_webhook_event(event, db) -> dict`:

- no `db.webhook_receipts` (legacy fakes) → dispatch best-effort without a
  receipt (backward-compatible fallback);
- `record_receipt`; if existing and `processed` → return
  `{"accepted": True, "event": ..., "duplicate": True, "result": stored}`;
- otherwise `mark_processing`, dispatch, and either `mark_processed` (return
  the result dict) or `mark_failed` (log, return `{"processed": False}`);
- only `parse_webhook_payload` failures stay 422 (validated before receipts).

`process_validation_result` / `process_publish_complete` keep their DB effects
and return `{"action": "rejected"|"completed"|"noop", "updated": n, ...}`.

## Test plan

- Repository (`tests/unit/storage/`): record + dedup + get; payload round-trip;
  attempts increment; processed/failed transitions + timestamps; IntegrityError
  fallback.
- Contract (`tests/unit/contracts/test_webhook_contract.py`): `delivery_id`
  optional/validated; key stable across timestamps; `id:` vs derived; distinct
  commits → distinct keys.
- Handler integration (`tests/integration/test_webhook_receipts.py`): processed
  duplicate returns stored result with no second transition; exception →
  `failed` + error, retry → `processed`; `received` crash state recovers; no
  receipts repo fallback still processes.
- Endpoint (`tests/test_webhook.py`): duplicate POST → 202 + `duplicate: true`,
  DB transition applied once; existing cases unchanged.
- Migration: new revision in `ALL_REVISIONS` +
  `REVISIONS_WITH_SUPPORTED_DOWNGRADE`; guard head bumped; round-trips green.

## Steps

### Step 0: Baseline + drift

Record the baseline count; STOP on drift/non-green.

### Step 1: Contract + tests

`delivery_id`, `extract_deploy_url`, `compute_delivery_key`; contract tests.

### Step 2: Model + migration + repository + tests

Mirror model/migration exactly; expose `db.webhook_receipts`; repository tests;
migration list/guard updates; `pytest tests/test_database_migrations.py tests/unit/storage/test_migration_guard.py -q`.

### Step 3: Handler + endpoint + tests

Receipt-first orchestration; process_* result dicts; endpoint delegation;
handler/endpoint tests.

### Step 4: Gates + docs

`make lint && make type && make test && make test-contracts && make test-boundaries`;
`make quality-gate`; `docs/PIPELINE_CONTRACTS.md`; `plans/060/todo.md`
annotations; ledger.

## Done criteria (machine-checkable)

- [ ] Baseline + full gates exit 0 (`test-contracts` and `test-boundaries`
      included — contract + storage/serving change class)
- [ ] `webhook_receipts` exists in models and migration; guard head updated;
      downgrade round-trip green
- [ ] Duplicate processed delivery returns the stored result and applies no
      second transition (test)
- [ ] Processing failure leaves a `failed` receipt with error + attempts,
      retry reachable (test)
- [ ] Invalid payload still 422; auth unchanged; always 202 otherwise
- [ ] `docs/PIPELINE_CONTRACTS.md` + plan checkboxes reconciled; ledger OK
- [ ] `git diff --name-only` only in-scope files

## STOP conditions

- Drift/baseline not clean.
- Any change to existing transition semantics, deploy-url behavior, auth, or
  the 422 path.
- The migration cannot round-trip on a fresh `create_all` DB.
- Existing webhook/contract tests must change behavior-wise (assertion edits
  beyond the new receipt fields are a STOP).

## Git workflow

- Branch: `advisor/060-phase-5a-webhook-receipts`.
- Commit: `feat(serving): durable webhook receipts with idempotent processing`.
- Do NOT push/PR unless instructed.
