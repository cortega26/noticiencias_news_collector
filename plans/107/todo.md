# TODO — Plan 107 (analytics baseline + cost/SLO)

Derived from `spec.md`. Mark when verified, not before.

## Step 0 — Baseline
- [ ] Drift check clean (or drift recorded as STOP)
- [ ] `make lint && make type && make test` green on clean tree (or red recorded)

## Step 1 — Plausible analytics
- [ ] `src/config.yaml` analytics ID set (frontend repo)
- [ ] Preview page source contains analytics script, nothing else changed
- [ ] `npm run build + test:dist + check:search-budget` green, no CWV regression

## Step 2 — Cost report
- [ ] `scripts/ops/cost_report.py` emits valid JSON on seeded sample
- [ ] Unit tests added and passing; `make lint` clean

## Step 3 — SLO snapshot
- [ ] Baseline numbers captured (ingest %, source-fail %, PR pass %, perf ref)
- [ ] `make perf` exit 0 or clean SKIPPED

## Close-out
- [ ] `validate_plans_ledger.py` → OK
- [ ] `plans/README.md` row 107 updated
