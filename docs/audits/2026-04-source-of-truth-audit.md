# Source-Of-Truth Audit

Date: 2026-04-02  
Scope: backend repo, with cross-repo checks against `../noticiencias`

## Executive Summary

This audit rewrote the backend governance stack so it matches the current repository instead of a mix of constitutional language, monorepo assumptions, and outdated operational documents.

Main improvements:

- corrected the repo boundary to reflect two sibling repositories, not a hybrid monorepo
- rewrote the constitutional docs to stop overstating guarantees that the code does not fully enforce today
- updated the pipeline, CI, and runbook docs so they match the real workflows and commands
- clarified the cross-repo publication contract with the frontend and the current publication-state semantics

This mattered because the previous document set made it too easy to misread compatibility debt as a hard guarantee, and too easy to follow outdated operational paths.

## Document Inventory

### Updated

- `README.md`
- `docs/SOURCE_OF_TRUTH.md`
- `docs/ARCHITECTURE.md`
- `docs/PIPELINE_CONTRACTS.md`
- `docs/ci.md`
- `docs/ops/RUNBOOK.md`
- `context/INVARIANTS.md`
- `context/CONTRACTS.md`

### Created

- `docs/audits/2026-04-source-of-truth-audit.md`
- `docs/dev/source-of-truth-backlog.md`

### Left Unchanged

- `docs/AGENTS.md`
  - already the correct operational law for backend changes
- `docs/runbook.md`
- `docs/collector_runbook.md`
- `docs/operations.md`
- `docs/testing.md`
  - these are already current, narrow in scope, and better aligned than the legacy `docs/ops/RUNBOOK.md`

### Obsolete, Demoted, Or Misleading

- previous `docs/SOURCE_OF_TRUTH.md`
  - described the system as a hybrid monorepo and overstated a few guarantees
- previous `docs/ARCHITECTURE.md`
  - mixed accurate direction with law-like claims that were stronger than current enforcement
- previous `docs/PIPELINE_CONTRACTS.md`
  - presented target-state or UI-parity claims as settled reality
- previous `docs/ci.md`
  - listed check expectations that did not cleanly map to the current workflow graph
- previous `docs/ops/RUNBOOK.md`
  - had drifted far enough that it needed to be demoted to a compatibility pointer

## Reality Vs Documentation Gaps

### Claims That No Longer Matched Code

- The backend docs described the ecosystem as a monorepo-like system. In practice, backend and frontend are separate sibling repos.
- Some docs described publication identity as fully deterministic without acknowledging the current fallback to `collected_date` and finally current date.
- Some docs described operational entrypoints around `run_collector.py` generically even though current automation prefers `scripts/run_collector.py` and Make targets.
- CI docs did not accurately reflect the current job graph in `.github/workflows/ci.yml`.

### Important Facts Missing From Docs

- `PR_CREATED` is the backend publication-state boundary; final public publication is a frontend concern.
- `news_collector/contracts/frontend_schema.py` is a backend mirror of the frontend schema, not the render authority itself.
- `context/*` files are derived summaries, not constitutional sources.

### Conflicts Resolved

- repo-boundary language across README, source-of-truth docs, and architecture docs
- pipeline-vs-reality descriptions for export compatibility and publication semantics
- operational runbook path confusion between `docs/ops/RUNBOOK.md` and the newer focused runbooks

## Key Governance Improvements

- Documentation hierarchy is now explicit and grounded in actual files.
- Cross-repo ownership between backend publication orchestration and frontend rendering is now clear.
- Strong guarantees were narrowed to what the code really does today.
- Compatibility debt is now called out as debt instead of being silently blessed as architecture.
- Derived context files now clearly sit below the active governance docs.

## Recommended Follow-Up Backlog

- Split `RefineryEngine` into narrower collaborators so publication flow, image handling, and Git orchestration are not concentrated in one module.
- Remove the current-date fallback from canonical publication identity generation.
- Add stronger cross-repo automation for schema parity and publication-contract drift.
- Consolidate legacy entrypoints and docs once compatibility windows are intentionally closed.
