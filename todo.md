# Todo: Sequential implementation of plans 001-010

- [x] Read repository governance and the plans index.
- [x] Read Plan 001 and run its drift check.
- [x] Implement Plan 001 config and environment documentation changes.
- [x] Verify Plan 001 secret removal and environment override behavior.
- [x] Run Plan 001 regression gates (`make config-validate`, `make lint`).
- [x] Review the Plan 001 diff and update its final status.
- [x] Read Plan 002 and inspect the publication identity flow and tests.
- [x] Implement Plan 002 deterministic filesystem recovery behavior.
- [x] Add and run Plan 002 focused regression tests (27 passed).
- [x] Run Plan 002 lint, mypy, and boundary checks.
- [x] Confirm the 4 frontend audit failures independently as the pre-existing baseline.
- [x] Review the Plan 002 diff and record its blocked status.
- [x] Read Plan 003 and confirm the prompt's affirmative/negative phrases.
- [x] Implement the exact normalized council approval predicate.
- [x] Run focused council tests and regression gates for Plan 003.
- [x] Review the Plan 003 diff and update its final status.
- [x] Read Plan 004 and inspect the scorer formula and real keyword lists.
- [x] Add HeuristicScorer characterization tests without changing production code.
- [x] Run focused tests, coverage, lint, and regression checks for Plan 004.
- [x] Review the Plan 004 diff and update its final status.
- [x] Read Plan 005 and confirm the single Alembic head and serving query shape.
- [x] Add the ScoreLog composite index, idempotent migration, and index test.
- [x] Apply migrations and run Plan 005 storage/serving regression gates.
- [x] Review the Plan 005 diff and update its final status.
- [x] Read Plan 006 and confirm the stale hook path and absent `src/` directory.
- [x] Correct the pre-commit mypy path regex.
- [x] Validate config and regex; confirm the hook now runs on both intended files.
- [x] Resolve Plan 006 STOP: aligned the hook with the repository environment; later verification passed.
- [x] Record Plan 006 as blocked without changing hook arguments or unrelated type debt.
- [x] Read Plan 007 and establish the pyproject wheel-build baseline.
- [x] Confirm no active `setup.py` references or `aiohttp` imports, then remove `setup.py`.
- [x] Run post-removal build and detect setuptools package-discovery failure.
- [x] Restore `setup.py` exactly; entrypoint tests and lint remain green.
- [x] Resolve Plan 007 STOP with explicit package discovery in `pyproject.toml`; later wheel verification passed.
- [x] Record Plan 007 blocked status.
- [x] Read Plan 008 and inspect coordinator callers and existing loop tests.
- [x] Check persistence result, stop on explicit failure, and count only persisted batches.
- [x] Add failure and happy-path persistence tests.
- [x] Run Plan 008 focused, boundary, lint, type, and fast-suite checks.
- [x] Review the Plan 008 diff and update its final status.
- [x] Read and implement Plan 009 prompt-isolation and SSRF test/documentation hardening.
- [x] Verify Plan 009 focused tests, lint, official type targets, and fast suite.
- [x] Document and defer DNS pinning because it requires a cross-client transport rewrite.
- [x] Read Plan 010, run its drift check, and inspect cluster/API behavior.
- [x] Query current cluster cardinality and write the spike note.
- [x] Add the bounded read-only related-articles endpoint.
- [x] Add no-cluster, clustered-ordering, and not-found serving tests.
- [x] Run Plan 010 targeted and regression gates.
- [x] Review Plan 010 scope and update its final status.
- [x] Resolve Plan 006 by aligning pre-commit mypy with the repository environment.
- [x] Verify the Plan 006 hook and update its status.
- [x] Resolve Plan 007 with explicit setuptools package discovery.
- [x] Rebuild without `setup.py`, run entrypoint/lint checks, and update its status.
- [x] Diagnose the blocked Elias Thorne publication and identify all generic alt fallbacks.
- [x] Implement publication-safe alt normalization and regression tests.
- [x] Repair and publish the blocked article through front-end PR #106.
- [x] Run backend and front-end required validation gates; record baseline audit failures.


## Fix: portable runtime paths for GitHub Actions

- [x] Inspect the latest scheduled collector failure and confirm the repeated root cause.
- [x] Replace workstation-specific active paths with repository-relative values.
- [x] Add regression coverage that rejects absolute paths in `config.toml`.
- [x] Run the focused config tests and `make config-validate` in CI.
- [x] Confirm collector initialization and dry-run collection succeed in CI.


## CI baseline recovery and deep-audit campaign

- [x] Diagnose all failures from the first PR run.
- [x] Add the CI recovery specification and acceptance criteria.
- [x] Fix dry-run export data flow and add regression coverage.
- [x] Make frontend checkout selection deterministic.
- [x] Correct NO_WARN test coverage without weakening policy.
- [x] Resolve expired security suppressions with current advisory evidence.
- [x] Regenerate dependency locks mechanically.
- [x] Resolve Black, Ruff and mypy failures.
- [x] Remove the remaining workstation-specific governance path.
- [x] Run every gate that received a runner and resolve newly exposed repository failures; record F-0054 for the final-head runner outage.
- [ ] Re-run the scheduled collector after GitHub restores runner availability (F-0054).
- [x] Execute the equivalent deep audit on the last executable baseline.
- [x] Commit the complete audit report and prioritized findings backlog.


### E2E dry-run serialization follow-up

- [x] Capture bulk dry-run articles without database writes.
- [x] Add a targeted zero-persistence regression test.
- [x] Normalize structured article metadata for JSON export.
- [x] Write the export atomically.
- [x] Verify a non-empty schema-valid E2E export.
- [x] Remove the tracked workstation virtualenv from repository state.
- [x] Ignore `.venv/` and harden bootstrap against a missing recorded base interpreter.
- [x] Re-run Code Quality and confirm pip-audit emits reports for all three locks.


- [x] Intercept and restore source stats/circuit/feed metadata writes during dry-run.
- [x] Skip unsolicited source-health artifact writes during dry-run.
- [x] Return non-zero when export serialization or atomic replacement fails.
- [x] Test previous-export preservation and temporary-file cleanup on export failure.
- [x] Document and verify the trimmed-summary/content-500 fallback contract.


- [x] Raise all ten primary-lock packages to their published fixed versions.
- [x] Regenerate all lockfiles mechanically after the security floors change.
- [x] Confirm fail-closed pip-audit reports no unallowlisted primary-lock findings.


## Improve Deep closure follow-ups

- [x] Record F-0030 through F-0054 in the central findings ledger.
- [x] Reconcile the audit backlog with the authoritative ledger.
- [x] Scope PYSEC-2026-2132 to Semgrep's isolated Click dependency and add an expiry.
- [ ] Remove the Semgrep Click exception by 2026-08-31 or when upstream compatibility ships.
- [ ] Obtain owner-approved edits for the two policy-blocked privileged workflows (F-0042).
- [ ] Monitor the third-party 403 source subset (F-0048).
- [ ] Restore GitHub Actions runner availability and rerun the final matrix plus scheduled collector (F-0054).
