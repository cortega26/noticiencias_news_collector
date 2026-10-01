# TODO — webhook inbox pull

- [x] Storage: `WebhookReceiptRepository.list_receipts(after_id, limit)` + unit tests
- [x] Contract: `AdminWebhookReceipt` + `AdminWebhookReceiptEnvelope`
- [x] Serving: `GET /v1/admin/webhook/receipts` (admin auth, cursor, limit) + tests
- [x] Regenerate `openapi.json` + `api.d.ts`; `admin-contracts-check` green
- [x] Ops: `scripts/ops/pull_webhook_receipts.py` (paging, replay, dedupe,
      dry-run, exit codes) + 13 unit tests under `tests/unit/ops/`
- [x] Wire `make webhooks-pull`; opt-in pull in `admin_stack.sh`
      (`WEBHOOK_INBOX_PULL=1`)
- [x] Docs: RUNBOOK section, PIPELINE_CONTRACTS admin bullet, PRODUCT_FLOW note
- [x] ADR-0011: Accepted + decision recorded in place
- [x] Gates: lint, type (ratchet 93.04% vs 91.25%), test (3516 passed),
      contracts (171), boundaries (3), admin-test (45), admin contracts, docs,
      inventory
- [ ] Commit + PR
