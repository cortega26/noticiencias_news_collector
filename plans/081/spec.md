# Plan 081 — Workspace documentation reconciliation

Status: IN_PROGRESS. Date: 2026-09-04.

## Scope

Audit both sibling repositories' first-party documentation against current
source/configuration. Start with governance, source-of-truth, architecture,
contracts/invariants, README/contributor guides, operational runbooks, CI and
derived context. Inventory remaining documents and distinguish current guidance,
proposals, runtime prompts, published content and historical records.

Correct verified documentary drift; improve fact ownership, navigation and
operational precision. Preserve historical decisions, executable prompt content,
published articles, runtime behavior, and existing Plan 080 work. Do not turn
desired architecture into claims of already-implemented behavior. Performance
and scalability guidance must reference measured evidence or explicit constraints.

## Method and outputs

1. Inventory documentation in both repos; scan current documents for stale paths,
   commands, versions, contracts, conflicting authority and misleading guarantees.
2. Read current governing documents and relevant source; use existing doc/config
   checks as baseline. Check public frontend schema against the backend mirror.
3. Edit active prose and indexes; label legacy compatibility entry points rather
   than rewriting historical reports. Prefer linking canonical facts to copying
   version tables, pipeline stages or contract shapes into more documents.
4. Record coverage, findings, evidence, edits, limitations and validation in
   `tests/results.md`; retain a machine-readable inventory in `tests/inventory.json`.
5. Obtain the review required by backend governance after the major edit phase;
   record any tool limitation honestly.

## Acceptance and verification

- Current governance and onboarding agree with actual app entrypoints, SQLite
  support, authenticated admin mutations, lifecycle recovery, and CI commands.
- Cross-repo identity/content/callback responsibilities remain explicit and
  compatible. Proposed generated contracts are not described as already shipped.
- Current docs use portable repository-relative paths and distinguish PR creation,
  workflow completion, deployment acknowledgment, and public availability.
- Relevant broken links/legacy instructions are repaired or explicitly marked as
  history. Historical/archival records are preserved.
- Both documentation checks and backend plan ledger pass; frontend baseline
  `npm run lint` and `npm run validate:content` run as required by its governance.
  Run config docs and contract-sync checks for the claims audited. No runtime
  build/tests are required solely for backend prose edits.
- Review the final diff and record pre-existing/environmental failures without
  weakening checks or making unrelated code changes.

This task changes documentation only (backend change matrix: Low). Validation
uses existing scripts; no tests mirroring prose will be introduced.
