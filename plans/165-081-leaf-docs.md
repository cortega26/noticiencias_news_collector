# Plan 165: Finish plan 081's leaf-doc sweep

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 3967ef58..HEAD -- docs/ scripts/debugging/README.md news_collector/taxonomy/README.md plans/081/`
> Docs change often; if any listed file changed, read the live version before
> judging its claims (that is normal here — do not STOP just because it moved).

## Status

- **Priority**: P2 (finishes an IN_PROGRESS governance plan)
- **Effort**: M
- **Risk**: LOW (docs only)
- **Depends on**: none; 139/147/150/156 already touched some of these docs
- **Category**: documentation
- **Planned at**: commit `3967ef58`, 2026-10-19

## Why this matters

Plan 081 reconciled the high-authority docs but explicitly deferred a
line-by-line read of ~22 backend leaf docs (`plans/081/tests/results.md`,
"Remaining for a future session"). Their claims were never verified against the
code — exactly the class of drift the last passes kept finding (stale job names,
deleted files, wrong commands). This plan finishes that sweep and lets 081 close.

## Current state

- `plans/081/todo.md` — three unchecked items; the first is the leaf-doc sweep,
  the other two are "run checks/record evidence" and "finalize ledger status".
- `plans/081/tests/results.md:173-197` — the exact remaining list (backend):
  `docs/testing.md`, `docs/runbook.md`, `docs/collector_runbook.md`,
  `docs/operations.md`, `docs/database_deployment.md`, `docs/security.md`,
  `docs/api_examples.md`, `docs/EDITORIAL_MODES.md`,
  `docs/editorial_quality_system.md`, `docs/contracts_inventory.md`,
  `docs/common_output_format.md`, `docs/faq.md`, `docs/fixtures.md`,
  `docs/performance_baselines.md`, `docs/placeholder_policy.md`,
  `docs/release-checklist.md`, `docs/release_notes.md`,
  `docs/security_removal_plan.md`, `docs/runbooks/healthcheck.md`,
  `docs/strategic_features.md`, `docs/tools_audit_issues.md`, `perf/bench.md`,
  `scripts/debugging/README.md`, `news_collector/taxonomy/README.md`.
  The frontend docs in the same list are **out of scope** (this repo's rule
  forbids writing to the frontend).
- The automated gate `scripts/check_doc_drift.py` covers only 15 docs; it
  verifies paths/commands/invariants, not narrative claims.
- Several of these docs were edited recently (139 `docs/ci.md`/`testing`?,
  147 `contracts_inventory`/`runbook`, 150 `runbooks/healthcheck`,
  156 `docs/security`). Verify the **live** text.

## Commands you will need

| Purpose          | Command                                              | Provenance | Expected |
|------------------|------------------------------------------------------|------------|----------|
| Install          | `make bootstrap`                                     | declared   | exit 0   |
| Docs drift       | `make docs-check`                                    | declared   | exit 0   |
| Context          | `make context-validate`                              | declared   | exit 0   |
| Inventory        | `make inventory-refresh && make inventory-check`      | declared   | exit 0   |
| Ledger           | `make plans-ledger-check`                            | declared   | OK       |

Provenance: all `declared`.

## Scope

**In scope**: the 22 backend docs above, `scripts/debugging/README.md`,
`news_collector/taxonomy/README.md`, and (only at the end)
`plans/081/todo.md` + `plans/081/tests/results.md`.

**Out of scope**: the frontend repo (`../noticiencias` — read-only if you need
to cross-check, never edit), `docs/archive/**`, `docs/audits/**`, any code,
config, workflow, prompt or data file. Do not rewrite documents wholesale:
fix confirmed drift, mark history where a claim is obsolete, keep the author's
voice.

## Method (per document)

1. Read the doc end to end.
2. Extract every **verifiable claim**: file/dir paths, script names, `make`
   targets, CLI flags, workflow/job names, env vars, version numbers, schema
   fields, URLs to first-party paths.
3. Verify each claim against the live tree (`ls`, `grep`, `python -c`, read the
   script/config). Do not trust prose.
4. Classify: correct / stale / historical / product-decision-needed.
   - **stale** → fix the doc;
   - **historical** → label it as history (do not delete the record);
   - **product-decision-needed** → leave the text and list it in NOTES.
5. Record one line per doc in your report: `doc — claims checked — fixes`.

**Efficiency**: batch the verification (one `grep` can confirm many paths); do
not read code files you only need a symbol name from.

## Steps

1. Sweep the list in this order: `testing.md`, `runbook.md`,
   `collector_runbook.md`, `operations.md`, `database_deployment.md`,
   `security.md`, `api_examples.md`, `EDITORIAL_MODES.md`,
   `editorial_quality_system.md`, `contracts_inventory.md`,
   `common_output_format.md`, `faq.md`, `fixtures.md`,
   `performance_baselines.md`, `placeholder_policy.md`, `release-checklist.md`,
   `release_notes.md`, `security_removal_plan.md`, `runbooks/healthcheck.md`,
   `strategic_features.md`, `tools_audit_issues.md`, `perf/bench.md`,
   `scripts/debugging/README.md`, `news_collector/taxonomy/README.md`.
2. Fix every confirmed stale claim. Prefer links to canonical files over copied
   tables (plan 081's method).
3. Update `plans/081/todo.md`: check the leaf-doc item with a one-line note
   naming any doc left as history/decision.
4. Append a short "Leaf-doc sweep (2026-10-19)" section to
   `plans/081/tests/results.md`: docs read, confirmed drift fixed, decisions
   deferred, and the checks run.
5. Run the gates below; commit docs and the 081 evidence together.

**Verify**: `make docs-check`, `make context-validate`,
`make inventory-refresh && make inventory-check`, `make plans-ledger-check` → all
green; `git diff --name-only main...HEAD` lists only docs + `plans/081/*`.

## Done criteria

- [ ] All 22 backend leaf docs read; every claim either verified or fixed
- [ ] No code/config/workflow changes; no frontend edits
- [ ] `plans/081/todo.md` leaf-doc item checked with a one-line note
- [ ] `plans/081/tests/results.md` has the sweep evidence
- [ ] `make docs-check`, `make context-validate`, `make inventory-check`, `make plans-ledger-check` → exit 0
- [ ] Ledger rows 165 and 081 updated by the reviewer

## STOP conditions

- A "stale" claim is actually a **product decision** (e.g. a planned feature
  described as current) → report it; do not silently rewrite the roadmap.
- A doc's content conflicts with another active doc and the authority chain
  (`docs/SOURCE_OF_TRUTH.md`) does not resolve it → report both paths.
- Fixing a claim would require changing code or a config → report; do not.
- You cannot verify a claim cheaply (external service, deleted history) → mark
  it in NOTES rather than guessing.
