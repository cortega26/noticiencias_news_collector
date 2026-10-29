# Plan 207 implementation checklist

- [x] Confirm `origin/main`, canonical-checkout WIP, and that plan ID 207 is free.
- [x] Create this spec, todo, and verification plan before implementation.
- [x] Add backend workflow and admin API regression tests for typed progress,
      current step, collection phases, dry-run behavior, and advisory failures.
- [x] Instrument collection and publication boundaries and persist typed
      current-progress snapshots without changing workflow outcomes.
- [x] Update the admin UI for both run types; separate progress-update age from
      heartbeat age; retain the publication estimate semantics.
- [x] Regenerate OpenAPI and TypeScript contracts; update active workflow docs
      and the plans ledger.
- [x] Run required checks, isolated local workflow verification, and responsive
      browser smoke checks; review the final diff and preserved canonical WIP.

## Verification record

- `make lint`, `make type`, and `make test` passed. Both full suites reported
  4,564 passed, 40 skipped, and 193 deselected; the type command also passed
  its coverage ratchet (90.12% against an 88.44% baseline).
- `make test-contracts` (310 passed), `make test-boundaries` (3 passed),
  `make admin-contracts-check`, `make admin-test` (97 passed),
  `make admin-build`, and `make admin-lint` passed.
- `make docs-check`, `make inventory-check`, and `make plans-ledger-check`
  passed. `git diff --check` passed.
- Focused collection/publication workflow and API tests passed (289 total),
  using temporary SQLite databases and fake external adapters.
- The local admin smoke showed live collection and publication progress at
  desktop width with no console errors. At 375px the existing desktop-console
  prompt is shown; neither viewport has horizontal overflow.
- Implementation remains uncommitted on the isolated feature worktree; no
  external publication, push, merge, or deployment was performed.
