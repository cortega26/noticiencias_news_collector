# TODO — Plan 111 (health block-lite + semantic dedup)

Derived from `spec.md`. Mark when verified, not before.

## Step 0 — Baseline
- [ ] Drift check clean (or recorded); baseline gates green

## Step 1 — Health block-lite
- [ ] Disputed + health/keyword → hard block with error code; all else advisory
- [ ] Unit tests (4 cases); existing auditor tests green

## Step 2 — Semantic grouping
- [ ] Title+summary grouping, no new infra; triage surfaces groups
- [ ] Golden tests (merge + non-merge); FP rate logged

## Step 3 — Metrics + docs
- [ ] Merge/block rates recorded; `EDITORIAL_MODES.md` updated
- [ ] `make docs-check` green; `make quality-gate` green

## Close-out
- [ ] `validate_plans_ledger.py` → OK; row 111 updated
