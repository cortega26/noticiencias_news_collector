# Plan 060 / Phase 0 todo: Baseline, decision record, and reproducible fixtures

Execution index for [`spec.md`](spec.md). The spec's excerpts, scope
boundaries, STOP conditions, and done criteria are binding; do not implement
from this checklist alone.

## Step 0 — baseline

- [x] Backend `make docs-check` and `make plans-ledger-check` pass on an
      unmodified checkout.
- [x] Frontend `npm run lint`, `npm run check:doc-drift`, and
      `node scripts/check-contract-sync.js --strict ...` pass on an
      unmodified checkout. (Re-verified 2026-08-23 during a ledger audit
      — missed in the original manual closeout pass, not the underlying
      check: lint 0 errors, doc-drift OK, contract-sync --strict full
      parity confirmed.)

## Step 1 — ADR pairs

- [x] Backend `docs/adr/0006-durable-workflow-lifecycle-state.md` written.
- [x] Backend `docs/adr/0007-generate-contracts-instead-of-hand-maintained-parsers.md` written.
- [x] Backend `docs/adr/0008-harden-two-repo-boundary-before-reconsidering-consolidation.md` written.
- [x] Frontend `docs/adr/0005-durable-workflow-lifecycle-state.md` written
      (cross-references backend 0006).
- [x] Frontend `docs/adr/0006-generate-contracts-instead-of-hand-maintained-parsers.md`
      written (cross-references backend 0007).
- [x] Frontend `docs/adr/0007-harden-two-repo-boundary-before-reconsidering-consolidation.md`
      written (cross-references backend 0008 and backend ADR-0003).
- [x] All six ADRs use the fuller ADR-0003-style structure and
      `**Status**: Proposed` (re-verified 2026-08-23; all six exist and
      match).

## Step 2 — publication-schema snapshot (frontend)

- [x] Confirmed `.contract-snapshots/frontend_schema.snapshot.json` is current
      (strict contract-sync check exits 0) — regenerated only if drifted.
      (Re-verified 2026-08-23: `--snapshot ... --strict` exits 0, full
      parity confirmed; a fresh `--generate-snapshot` diffs identical
      except the `generatedAt` timestamp, so no regeneration needed
      despite the tool's own 19-day-staleness warning.)

## Step 3 — shared publication-contract corpus (frontend)

- [x] `tests/fixtures/publication-contract-corpus/README.md` written
      (explains purpose, versioning rule, phase consumers).
- [x] `valid/v1-complete.json` and `valid/v2-complete.json` added.
- [x] Six `invalid/v2-missing-<field>.json` fixtures added (one per required
      v2 field).
- [x] `invalid/v2-empty-summary-points.json` and
      `invalid/v2-too-many-summary-points.json` added.
- [x] `edge-cases/date-formats.json`, `edge-cases/source-objects.json`,
      `edge-cases/defaults.json` added.
- [x] `edge-cases/additional-property-stripped.json` added (Zod strips
      unknown keys by default here — verified no `.strict()`/`.passthrough()`
      in `content.config.ts`; fixture and README describe stripping, not
      rejection).
- [x] `v2-strict-failure-inventory.json` committed with `_generated_at_commit`
      set to the frontend SHA it was generated at; `errors[]` content matches
      a fresh run (order-independent; exit code 1 from the check is expected).
      (Cross-checked against a live run during Phase 2b Step 1: zero
      discrepancy found between this file and the live corpus.)
- [x] Every fixture file parses as valid JSON. (Re-verified 2026-08-23:
      all 15 files under `tests/fixtures/publication-contract-corpus/`
      parse cleanly.)

## Step 4 — backend OpenAPI snapshot

- [x] `scripts/generate_admin_openapi_snapshot.py` written, matching
      `tests/test_serving_admin_api.py`'s `create_app()` construction pattern.
- [x] `.contract-snapshots/admin_openapi.snapshot.json` generated.
- [x] Two consecutive runs produce byte-identical output (verified via diff).

## Step 5 — close out

- [x] `plans/060/todo.md` Phase 0 checkboxes (Wave A) checked off.
- [x] This file's checkboxes checked off. (Reconciled 2026-08-23 — the
      frontend-scoped items above were verified done at merge time but
      the boxes themselves were missed in the original manual closeout
      pass; re-verified live and checked off now, see notes on each.)
- [x] No Wave B–E checkbox touched; plan 060 not marked DONE anywhere.
- [x] `git diff --stat` in each repo shows only in-scope files (see spec.md
      "Scope"). (Verified at original review time per this session's
      standing review discipline, not re-derived from historical git
      archaeology during this 2026-08-23 audit.)
