# Plan 060 / Phase 5a todo — Durable webhook receipts

Execution index for [`spec.md`](spec.md). The spec's scope boundaries, STOP
conditions, and done criteria are binding; do not implement from this checklist
alone.

## Step 0 — baseline + drift

- [x] Drift check clean at `8dd3981` (2026-09-25: HEAD == `8dd3981`, in-scope
      diff empty).
- [x] Baseline recorded for the webhook/storage/contract suites (2026-09-25:
      `pytest tests/test_webhook.py
      tests/integration/test_publication_callback_contract.py
      tests/unit/storage tests/unit/contracts/test_webhook_contract.py -q`
      → 245 passed including the new receipt suites).

## Step 1 — contract

- [x] `delivery_id` optional field + validator (`<=128` chars, non-blank).
- [x] `extract_deploy_url` + `compute_delivery_key` (stable fields only;
      `timestamp` deliberately excluded).
- [x] contract tests (optional/validated/key stability/deploy-url).

## Step 2 — model + migration + repository

- [x] `WebhookReceipt` model + status CHECK + unique key + status index.
- [x] NEW migration `f2a9c1d4e6b7_add_webhook_receipts` (down_revision
      `e3f168a66d38`, idempotent, complete downgrade).
- [x] `WebhookReceiptRepository` + `db.webhook_receipts`.
- [x] repository tests incl. unique-index race fallback.
- [x] migration lists + guard head updated; migration tests green.

## Step 3 — handler + endpoint

- [x] `handle_webhook_event` receipt-first orchestration.
- [x] `process_*` return result dicts.
- [x] endpoint delegates; 202/422/auth unchanged.
- [x] handler integration tests (duplicate/failed/retry/crash/legacy fallback).
- [x] endpoint duplicate test.

## Step 4 — gates + docs

- [x] `make lint && make test && make test-contracts && make test-boundaries`
      (2026-09-25: lint OK; test 3270 passed; contracts 171 passed; boundaries
      3 passed).
- [x] `make type` + `make quality-gate` (+ `make verify-ci` if time allows).
      (2026-09-25: type 3283 passed, coverage ratchet OK at 92.32%; quality
      gate all snapshots valid; security/config-docs/docs checks OK. The
      endpoint docstring change required `make admin-contracts-generate` to
      refresh `apps/admin/openapi.json` + generated TS before type went green.)
- [x] `docs/PIPELINE_CONTRACTS.md` updated.
- [x] `plans/060/todo.md` Phase 5 annotations.
- [x] `.venv/bin/python scripts/validate_plans_ledger.py` OK.
