# Plan 081 checklist

- [x] Read both governance entry points and backend engineering instructions.
- [x] Inventory documentation and establish baseline doc/config/contract checks
      (inventory pre-existed; baseline checks run and confirmed green before edits).
- [x] Reconcile governing docs, architecture, contracts and invariants
      (SOURCE_OF_TRUTH, ARCHITECTURE, PIPELINE_CONTRACTS, PRODUCT_FLOW, ci.md,
      INDEX.md, context/* — fixed INDEX.md ADR gaps and ci.md missing workflow).
- [x] Reconcile README/contributor guides, operations, CI and derived context
      (both repos' README/CONTRIBUTING checked; frontend README historical
      labeling fixed; frontend AGENTS.md stray tool-memory block removed).
- [x] Review remaining active documentation, links and historical boundaries
      — leaf-doc sweep completed 2026-10-19 (plan 165): all 24 backend leaf docs
      read and verified; history-labeled `perf/bench.md`,
      `docs/strategic_features.md`, `docs/security_removal_plan.md` and the
      taxonomy README backfill note; no product-decision claims rewritten.
- [x] Review edits; run required checks; record coverage and limitations
      — checks run and recorded (docs-check 15, context-validate, inventory,
      ledger); spec-vs-implementation review outcome in results.md.
- [x] Finalize audit evidence and ledger status — results.md carries the full
      evidence; closed DONE 2026-10-19 after plan 165 finished the leaf-doc sweep.
