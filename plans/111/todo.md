# TODO — Plan 111 (health block-lite + semantic dedup)

Derived from `spec.md`. Mark when verified, not before.

## Step 0 — Baseline (DONE 2026-09-16)
- [x] Drift check clean; both repos on main, trees clean

## Step 1 — Health block-lite (DONE 2026-09-16, corrected on evidence)
- [x] Found universal disputed block already exists — kept; escalated plan-083 overclaims to hard `editorial_capability_overclaim` block in health scope only
- [x] `editorial/health_scope.py` canonical triggers shared by auditor (no drift); pure `_capability_overclaim_block` helper
- [x] Unit tests (predicate matrix + gate matrix); 350 editorial tests green, no fixture fallout

## Step 2 — Semantic grouping (DONE 2026-09-16, corrected on evidence)
- [x] MinHash measured and rejected (paraphrase ~0.0); word+bigram TF cosine, stdlib-only, threshold 0.30 with measured margins
- [x] `utils/similarity.py` + golden tests (merge / distinct / same-topic-different-finding / degenerate)
- [x] Surfaced per-page in triage (`similar_group_id/size`, master = top-ranked) + GUI chip; serving test green

## Step 3 — Metrics + docs (DONE 2026-09-16)
- [x] `EDITORIAL_MODES.md` pre-PR hard gates section; `make docs-check` green

## Close-out (DONE 2026-09-16)
- [x] Full gates: lint/test(2640)/contracts(164)/boundaries/quality-gate green; GUI vitest 35 + astro check clean
- [x] `validate_plans_ledger.py` → OK; row 111 updated
