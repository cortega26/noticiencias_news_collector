# Plan 060 / Phase 5b todo — Attempt events and stale reconciliation

Execution index for [`spec.md`](spec.md). The spec's scope boundaries, STOP
conditions, and done criteria are binding; do not implement from this
checklist alone.

## Step 0 — baseline + drift

- [x] Drift check clean at `88dd9c4` (branch created; in-scope diff empty).
- [x] Baseline recorded (2026-09-25: `tests/unit/storage
      tests/integration/test_webhook_receipts.py
      tests/integration/test_publication_callback_contract.py` → 162
      passed).

## Step 1 — storage: legality + events + queries

- [x] `LEGAL_PUBLICATION_TRANSITIONS` + `is_legal_publication_transition`
      (PUBLISHING → PR_CREATED/REJECTED/COMPLETED legal by plan-3c race
      proof; terminals permit nothing).
- [x] `PublicationEventView` + `record_publication_event` +
      `get_publication_events_for_attempt`.
- [x] `apply_publication_transition` (legality + CAS + event, one transaction;
      illegal/unknown-type = no write at all).
- [x] `find_latest_publication_attempt_by_refinery_id`.
- [x] `list_stale_publication_attempts`.
- [x] event/legality unit tests (21 passed;
      `tests/unit/storage/test_lifecycle_publication_events.py`).

## Step 2 — dual-write event recording

- [x] `_dual_write_pr_created` → `pr_created` event (CAS path and fallback
      insert both audited).
- [x] `_dual_write_transition` → `rejected`/`deployed` events; callers pass
      bounded `reason`/`deploy_url` details.
- [x] dual-write tests extended; one monkeypatch target updated from
      `transition_publication_attempt` to `apply_publication_transition` (the
      refactor moved the call; assertions unchanged). 56 targeted tests green.

## Step 3 — callback module move + check_passed

- [x] NEW `logic/workflows/publication_callbacks.py` (apply_* bodies).
- [x] serving `process_*` delegates (patch/direct-call compatibility preserved;
      `test_webhook_receipts.py` patch target still intercepts).
- [x] validation pass records `check_passed` best-effort (unknown/terminal
      attempt = no row; lifecycle failure swallowed; no `lifecycle` attr =
      no-op).
- [x] callback unit tests (10 in
      `tests/unit/logic/workflows/test_publication_callbacks.py`).

## Step 4 — reconciler + ops script

- [x] `list_unprocessed_receipts` on the receipt repository.
- [x] NEW `logic/workflows/publication_reconciliation.py` (replay, evidence
      rules, dry run, `workflow_runs` audit row).
- [x] NEW `scripts/ops/reconcile_publication_attempts.py`.
- [x] unit + integration tests: failed publish/validation replay, replay
      failure stays retryable, legacy completed + deploy URL repair, missing
      deploy evidence refused, legacy rejected repair, terminal skipped,
      stale open PR untouched, malformed/unmatched receipts reported, dry-run
      writes nothing, audit rows (13 integration + 2 script tests; 200 green
      across the touched suites).

## Step 5 — gates + docs

- [x] `make lint && make type && make test && make test-contracts && make
      test-boundaries` (2026-09-25: lint OK; type 3334 passed, coverage
      ratchet 92.48%; test 3321 passed; contracts 171; boundaries 3).
- [x] `make quality-gate` (all snapshots valid) + `make security`
      (pip-audit/bandit/gitleaks clean after adding the rule-scoped
      `compute_delivery_key` gitleaks allowlist — the new 5a commit's
      `key = compute_delivery_key` lines matched `generic-api-key` as a false
      positive).
- [x] `docs/PIPELINE_CONTRACTS.md` updated (audited legal transitions +
      reconciler semantics).
- [x] `plans/060/todo.md` Phase 5 items 3/4/6 annotated.
- [x] `.venv/bin/python scripts/validate_plans_ledger.py` OK.
