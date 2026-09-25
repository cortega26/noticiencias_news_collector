# Plan 060 / Phase 5c todo — Dashboard health evidence API

Execution index for [`spec.md`](spec.md). The spec's scope boundaries, STOP
conditions, and done criteria are binding; do not implement from this
checklist alone.

## Step 0 — baseline + drift

- [x] Drift check clean at `6d0ad4c` (branch created; in-scope diff empty).
- [x] Baseline recorded (2026-09-25: `tests/test_serving_admin_api.py
      tests/unit/storage` → 264 passed).

## Step 1 — contract + repository aggregates

- [x] `AdminDashboardEvidence` + `AdminDashboardHealthEnvelope`.
- [x] lifecycle: attempts-by-state, `oldest_attempt_started_at(state)`,
      latest attempt created, events-by-type, latest event.
- [x] receipts: counts-by-status, oldest unprocessed, latest receipt.
- [x] repository aggregate unit tests (empty + populated; 38 in the two
      suites).

## Step 2 — builder + endpoint

- [x] NEW `serving/dashboard_health.py` with the status rules
      (empty → `unknown`/`evidence="none"`; stuck PUBLISHING → `fail`; stale
      PR_CREATED → `warning`; failed receipt → `fail`; pending → `warning`;
      rejected event → `warning`; otherwise `pass`).
- [x] `GET /v1/admin/dashboard/health` (admin auth, typed response).
- [x] builder unit tests (12) + endpoint auth/shape/real-record tests
      (`tests/test_serving_admin_api.py`).

## Step 3 — gates + artifacts + docs

- [x] `make admin-contracts-generate` (additive diff only:
      `apps/admin/openapi.json` + generated TS; contract tests green).
- [x] `make lint && make type && make test && make test-contracts && make
      test-boundaries` (2026-09-25: lint OK; type 3358 passed, coverage
      ratchet 92.38%; test 3345; contracts 171; boundaries 3).
- [x] `make quality-gate` + `make security` + docs/config-docs checks.
- [x] `docs/PIPELINE_CONTRACTS.md` updated.
- [x] `plans/060/todo.md` Phase 5 item 5 annotated (backend half; 5d
      remains).
- [x] `.venv/bin/python scripts/validate_plans_ledger.py` OK.
