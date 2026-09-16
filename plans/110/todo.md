# TODO — Plan 110 (source-health visibility)

Derived from `spec.md`. Mark when verified, not before.

## Step 0 — Baseline
- [ ] Drift check clean (or recorded); baseline gates green

## Step 1 — Visibility
- [ ] Cooldown/taxonomy/operational_state surfaced in admin health + Sources page
- [ ] Boundary tests; `make test-boundaries` green

## Step 2 — Detectors resolution
- [ ] Detectors/canary wired into runtime OR removed with rationale (no partial state)
- [ ] `make test` green

## Step 3 — Concurrency + perf
- [ ] Limit 1→3, domain delays intact; before/after numbers recorded
- [ ] `make perf` exit 0 or clean SKIPPED

## Close-out
- [ ] `validate_plans_ledger.py` → OK; row 110 updated
