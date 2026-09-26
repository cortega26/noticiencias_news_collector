# Plan 080 checklist

Phases 0-2 done and merged (stateful workflow tests; generated admin response
contracts + drift gate). Phase 3 (offline editorial replay pilot) and Phase 4
(delivery) remain. Mark a phase complete only after its acceptance evidence and
required review exist. (Header reconciled 2026-09-26 — it previously claimed
implementation had not started, contradicting the checked phases below.)

## Planning delivery

- [x] Read backend governance, selected code paths and prior plan decisions.
- [x] Verify official Hypothesis, FastAPI, OpenAPI TypeScript and Promptfoo APIs.
- [x] Select bounded deliverables and record deferred decisions.
- [x] Write phase specifications, acceptance criteria and handoff prompt.
- [x] Complete local consistency review and documentation sanity checks.
- [ ] Independent planning review — attempted; reviewer could not run because
  the account usage limit was reached. See `tests/planning-results.md`.

## Phase 0 — execution preflight

- [x] Record checkout versions, dirty files, assigned scope and baseline checks.
  See `tests/baseline.md`.
- [x] Reconcile any code changes since planning; read the assigned phase's docs.

## Phase 1 — workflow stateful tests

- [x] Add isolated SQLite machine, controlled clock and no-op dispatch.
- [x] Add independent expected-state model and actions for both run types.
- [x] Prove W1 single-flight/isolation and W2 exact expiry boundaries.
- [x] Prove W3 queued/NULL-heartbeat recovery modes and W4 terminal stability.
- [x] Prove W5 cleanup and fault sensitivity; retain existing concurrency tests.
- [x] Run required gates; record `tests/phase-1-results.md`; resolve fresh review.
  Gates: new file + both unit test files (55 passed), admin API tests
  (65 passed), `make lint` (pass), `make type` (exit nonzero — mypy pass
  and coverage ratchet pass verified independently, but the target's own
  pytest step has 5 pre-existing/unrelated failures, each independently
  reproduced in isolation — see `tests/phase-1-results.md`), `make test`
  (2364 passed), `make test-boundaries` (3
  passed). No production code left modified. Phase 2/3 not started.

## Phase 2 — generated admin response contracts

- [x] Add/test isolated deterministic schema export and nonmutating check modes.
- [x] Pin generator, commit schema/types, replace four response interfaces.
- [x] Add Make/npm commands and dedicated CI job with correct triggers.
- [x] Prove A1–A5 including separate stale-schema and stale-types failures.
- [x] Update active docs and exact Plan 060 partial progress.
- [x] Run required gates; record `tests/phase-2-results.md`; resolve fresh review.

## Phase 3 — offline editorial replay pilot

- [ ] Define validated case/output records with provenance; create six controls.
- [ ] Reuse public Markdown guardrail validator and add narrow case assertions.
- [ ] Prepare deterministic paired replay config and manifest.
- [ ] Pin isolated Promptfoo tooling; add optional install/replay entry points.
- [ ] Prove E1–E5 with passing and expected-failing offline integrations.
- [ ] Record adoption or justified no-go; remove unused pilot dependencies on no-go.
- [ ] Run required gates; record `tests/phase-3-results.md`; resolve fresh review.

## Phase 4 — delivery

- [ ] Review final scope, tests, generated artifacts and CI wiring against spec.
- [ ] Verify required checks against final relevant code; preserve limitations.
- [ ] Record V1 and exact completed/pending acceptance IDs in final evidence.
- [ ] Update ledger/status without marking deferred items or Plan 060 complete.
