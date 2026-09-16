# TODO — Plan 110 (source-health visibility)

Derived from `spec.md`. Mark when verified, not before.

## Step 0 — Baseline
- [x] Drift check clean; `make lint` green; `make type` 2602 passed + 4 pre-existing e2e frontend_dist_failure (proven pre-existing via pre-007 worktree, out of scope)

## Step 1 — Visibility (DONE 2026-09-16, rescoped on evidence)
- [x] Found Sources page + `/v1/admin/sources` already show COOLDOWN distinctly — pinned with regression test instead of duplicating
- [x] `SourceRepository.get_all_circuit_states()` (1 SELECT) + DB forwarder; both endpoints use the bulk map (58→1 SELECTs, revert-proven)
- [x] `SourceHealthRecord` +3 optional circuit fields; health endpoint merges live state (Streamlit path covered); `make test-boundaries` green

## Step 2 — Detectors resolution (DONE 2026-09-16)
- [x] Verdict: keep offline tooling, kill the fiction — `sources.auto_suppressed`/`suppressed_sources` renamed to `suppression_candidates`/`suppression_candidate_sources` + docstring (actuation stays with the breaker); runtime wiring explicitly rejected; monitoring tests green

## Step 3 — Concurrency + perf (DONE 2026-09-16, corrected on evidence)
- [x] Found `collection.max_concurrent_requests=1` has NO consumer (live knob is `max_concurrent_sources=10`; politeness is per-request) — raising it would be placebo; documented RESERVED in schema + regenerated config docs instead
- [x] Real perf proof: `tests/perf/test_admin_sources_perf.py` (≤1 SELECT regardless of catalog size); `make perf` green

## Close-out (DONE 2026-09-16)
- [x] Full gates green (same run as 109); perf gate includes new sources ≤1-SELECT test (58→1 revert-proven)
- [x] `validate_plans_ledger.py` → OK; rows 109/110 updated
