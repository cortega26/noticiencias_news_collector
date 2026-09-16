# TODO — Plan 109 (batch publication)

Derived from `spec.md`. Mark when verified, not before.

## Step 0 — Baseline
- [ ] Drift check on pipeline/serving/admin paths clean (or recorded)
- [ ] Baseline gates green; identity golden proof noted

## Step 1 — Contract + pipeline
- [ ] Batch shapes in `contracts/admin.py`; adapter-only mapping
- [ ] Batch entry aggregates per-item outcomes; attempts persisted per id
- [ ] New unit tests (cap, empty, one-bad-item); `make test-contracts` green

## Step 2 — Serving wrapper
- [ ] Thin endpoint, 409/404/lease semantics preserved
- [ ] Boundary tests; `make test-boundaries` green

## Step 3 — Admin GUI
- [ ] Triage multi-select + batch status; vitest green

## Close-out
- [ ] No identity value changed for prior publishes; `make quality-gate` green
- [ ] `validate_plans_ledger.py` → OK; row 109 updated
