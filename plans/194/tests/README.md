# Fresh verification — 2026-10-25

These are fresh results on current backend main plus the admin preflight port, not the older root task's historical counts. Logs are retained under `/tmp/noticiencias-backend-sync-checks-20261025/`.

- Targeted real-npm startup regressions: 8 passed, including invalid trees blocking both launchers before services start. Independently repeated: 8 passed.
- `make lint`, `make type`, `make test`, `make test-boundaries`, `make docs-check` and `make inventory-check`: passed. Unit run: 4,447 passed, 40 skipped, 190 deselected. Skips include explicit live-network/provider opt-ins and environment-dependent frontend-discovery tests.
- Explicit `EXPECTED_FRONTEND_SCHEMA` plus `make test-contracts`: 310 passed against the real current frontend schema; coverage 91.23%, above the 80% contract threshold.
- Admin lint, test and build: passed; 96 client tests. Real installed dependency-tree preflight: passed.
- `make prepush`: passed. Unit run 4,447 passed/40 skipped; additional suite groups 108 passed/9 skipped, 189 passed, 14 passed and 9 performance tests. Quality gate: all three snapshots valid. No new provider experiment or live collection was run.
- Independent review: no P1/P2 findings in the startup fix. Closure draft is not ready (45 tests passed, 10 failed); Buffer draft has incompatible client/export contracts. Neither draft is activated on main.
- Both repository histories and all publishable candidate files passed redacted secret scans with zero findings. Frontend: 20 exact remote preservation/source refs verified. Backend: four exact refs verified. Patches reconstruct selected original source files byte for byte at recorded base commits.

Restricted private originals and all-ref bundles are retained at `/home/carlos/.local/share/codex/task-backups/noticiencias-sync-20261025T162223Z/`. Live credentials were excluded from public snapshots; effective local configuration was verified unchanged after removing serialized credentials. Rotation of the exposed credentials remains an operator action, not a completed step.

Ready source fix and preservation refs are distinct; the delivery receipts below record the completed actions.

The first PR CI run caught a documentation-path regression: Python-only jobs do not install the admin dependencies, so the new runbook must not assert that their generated directory already exists. The failure was reproduced by temporarily moving only this task's dependency directory; the wording was corrected without weakening the doc checker. Both the doc command and its live-repository regression test were then rerun with dependencies absent.

## Integration and source synchronization receipts

- [PR #392](https://github.com/cortega26/noticiencias_news_collector/pull/392) merged exact reviewed head `c562a283b880e31c92fb21eb574148f5dd59d770` as `ac5bd24bdf7e884fb026ecd0038c48b938e875a8`, after all 22 checks completed successfully or neutrally. Reviews and inline threads were read separately; no unresolved findings were present.
- Post-merge validation of `ac5bd24b`: [CI](https://github.com/cortega26/noticiencias_news_collector/actions/runs/40219479222), [Code Quality](https://github.com/cortega26/noticiencias_news_collector/actions/runs/40219479249), [docs](https://github.com/cortega26/noticiencias_news_collector/actions/runs/40219479206), [E2E contract](https://github.com/cortega26/noticiencias_news_collector/actions/runs/40219479218) and master synchronization all completed successfully. CI includes wheel/Docker build and Docker smoke test.
- Independent documentation-closure review found no P1/P2 issues and independently reconciled the 88-entry disposition and exact-original/normalized export evidence.
- Canonical frontend main was clean and matched live origin at `172d9ad3f58701acd65317880d6059a600ede3f8`; canonical backend main was clean and matched live origin at merge `ac5bd24b`. Backend bootstrap, locked admin dependency installation and actual offline preflight passed in the canonical checkout. Effective local scoring weights remained `0.05` source credibility and `0.15` recency, in ignored environment configuration.
- The dated [source synchronization audit](synchronization.json) accounts for all 88 initial entries and 24 exact remote preservation refs. It captures five clean checkouts after removing four obsolete/task worktrees using normal Git removal. The remaining implementation worktree is temporary; the final documentation merge and its cleanup are verified separately in the delivery response.
- [Backend local snapshot](https://github.com/cortega26/noticiencias_news_collector/tree/archive/local-main-sync-20261025), head `66902bf45e1993afe321dab966ea29da76a97d9e`: original pending work with redacted local configuration, historical experiment/runtime records and reconstructible unfinished closure/editorial-image patches. The original runtime export is preserved in `39eade9b`; its later EOF normalization leaves parsed JSON unchanged.
- [Frontend draft snapshot](https://github.com/cortega26/noticiencias/tree/archive/worktree-drafts-20261025), head `cf15e9ffd9d16e4a028d3b061a8a4900df99786c`: reconstructible incompatible Buffer draft. Neither archive is a release candidate.
- Selected draft sources were reconstructed byte for byte against their recorded bases before original worktree cleanup. Runtime/dependency artifacts, consistent SQLite backups, original environment files and all-ref Git bundles remain in the restricted private backup. No live service was stopped and no collection, publication or provider experiment was triggered.

This completes source synchronization, not the broader AdSense readiness program. Exposed-credential rotation remains an operator action; unfinished drafts remain explicitly unfinished.
