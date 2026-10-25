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

Ready source fix and preservation refs are distinct. Final CI, merge and checkout-cleanup receipts will be recorded separately after those actions actually occur.

The first PR CI run caught a documentation-path regression: Python-only jobs do not install the admin dependencies, so the new runbook must not assert that their generated directory already exists. The failure was reproduced by temporarily moving only this task's dependency directory; the wording was corrected without weakening the doc checker. Both the doc command and its live-repository regression test were then rerun with dependencies absent.
