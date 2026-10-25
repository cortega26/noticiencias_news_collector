# Plan 194 — synchronize local work and deliver admin dependency preflight

## Goal and scope

The owner requests that both repositories and all local pending work be synchronized. Preserve each source change before cleaning any checkout. Integrate the completed admin dependency fix into current backend main; retain unfinished experiments, historical runtime evidence and feature drafts on explicitly labelled remote preservation branches. Do not merge obsolete locks, old article rewrites, unfinished workflow features or experimental routing into production merely to obtain a clean status.

Credentials and machine-specific overrides belong in ignored local configuration. Never publish live credentials. Preserve the original private files and hashes in a restricted backup before migration. Record the need to rotate credentials exposed by the initial unredacted local diff; do not revoke or silently change service credentials during source synchronization.

## Admin preflight behavior

Both `make admin` and `make admin-dev` run the shared offline `npm ls --depth=0 --include=dev` check before starting either service. Missing, incomplete or incompatible dependency trees fail with an explicit `make admin-install` recovery instruction. A valid tree passes without installation, network access or lockfile changes. Existing operator processes remain running.

Files: `scripts/dev/check_admin_dependencies.sh`, `scripts/dev/admin_stack.sh`, `Makefile`, `tests/scripts/test_admin_dependencies.py`, `docs/RUNBOOK_LOCAL_DEV.md`, plan documentation and inventory as required. Development-stack orchestration is high risk; no API, publication, schema, dependency or routing change is intended in this PR.

## Synchronization invariants

- Every initially modified/untracked source file is accounted for by a verified private original plus a sanitized committed remote copy, or an explicitly identified ignored runtime/dependency artifact.
- Preserve historical benchmark results as historical; do not fabricate missing human judgments or claim those results authorize a routing change.
- Preserve each local-only commit on an appropriate remote ref before branch cleanup. Do not force-push, reset away edits or overwrite concurrent work.
- Canonical front/backend main are clean and equal their remote main refs after integration. Retained draft worktrees are clean and track exact matching preservation refs.
- No collection, article publication, subscriber creation, outreach or new provider experiment is run as part of this synchronization.

## Verification

1. Restricted backup manifest records original paths, file hashes, worktree heads and patches. Scan public candidates and local-only history with redacted secret reports before pushing.
2. Eight existing admin dependency regression cases use real npm against offline fixture trees and verify fail-before-start behavior and successful GUI startup.
3. Run backend lint, type, tests, boundary tests, docs/inventory checks and required pre-push validation. Run admin lint/tests/build as the affected startup targets serve that app. Distinguish historical test counts from fresh results.
4. Independent review against this spec before integration; address all P1/P2 findings.
5. Verify exact-head CI, merge the ready fix and verify main CI. This developer-startup repair does not require a hosted backend deployment.
6. Re-read all worktree statuses and remote refs after cleanup; report remaining private operational actions and any incomplete feature drafts accurately.
