# Plan 060 / Phase 0 todo: Baseline, decision record, and reproducible fixtures

Execution index for [`spec.md`](spec.md). The spec's excerpts, scope
boundaries, STOP conditions, and done criteria are binding; do not implement
from this checklist alone.

## Step 0 — baseline

- [ ] Backend `make docs-check` and `make plans-ledger-check` pass on an
      unmodified checkout.
- [ ] Frontend `npm run lint`, `npm run check:doc-drift`, and
      `node scripts/check-contract-sync.js --strict ...` pass on an
      unmodified checkout.

## Step 1 — ADR pairs

- [ ] Backend `docs/adr/0006-durable-workflow-lifecycle-state.md` written.
- [ ] Backend `docs/adr/0007-generate-contracts-instead-of-hand-maintained-parsers.md` written.
- [ ] Backend `docs/adr/0008-harden-two-repo-boundary-before-reconsidering-consolidation.md` written.
- [ ] Frontend `docs/adr/0005-durable-workflow-lifecycle-state.md` written
      (cross-references backend 0006).
- [ ] Frontend `docs/adr/0006-generate-contracts-instead-of-hand-maintained-parsers.md`
      written (cross-references backend 0007).
- [ ] Frontend `docs/adr/0007-harden-two-repo-boundary-before-reconsidering-consolidation.md`
      written (cross-references backend 0008 and backend ADR-0003).
- [ ] All six ADRs use the fuller ADR-0003-style structure and `Status: Proposed`.

## Step 2 — publication-schema snapshot (frontend)

- [ ] Confirmed `.contract-snapshots/frontend_schema.snapshot.json` is current
      (strict contract-sync check exits 0) — regenerated only if drifted.

## Step 3 — shared publication-contract corpus (frontend)

- [ ] `tests/fixtures/publication-contract-corpus/README.md` written
      (explains purpose, versioning rule, phase consumers).
- [ ] `valid/v1-complete.json` and `valid/v2-complete.json` added.
- [ ] Six `invalid/v2-missing-<field>.json` fixtures added (one per required
      v2 field).
- [ ] `invalid/v2-empty-summary-points.json` and
      `invalid/v2-too-many-summary-points.json` added.
- [ ] `edge-cases/date-formats.json`, `edge-cases/source-objects.json`,
      `edge-cases/defaults.json` added.
- [ ] `edge-cases/additional-property-stripped.json` added (Zod strips
      unknown keys by default here — verified no `.strict()`/`.passthrough()`
      in `content.config.ts`; fixture and README describe stripping, not
      rejection).
- [ ] `v2-strict-failure-inventory.json` committed with `_generated_at_commit`
      set to the frontend SHA it was generated at; `errors[]` content matches
      a fresh run (order-independent; exit code 1 from the check is expected).
- [ ] Every fixture file parses as valid JSON.

## Step 4 — backend OpenAPI snapshot

- [ ] `scripts/generate_admin_openapi_snapshot.py` written, matching
      `tests/test_serving_admin_api.py`'s `create_app()` construction pattern.
- [ ] `.contract-snapshots/admin_openapi.snapshot.json` generated.
- [ ] Two consecutive runs produce byte-identical output (verified via diff).

## Step 5 — close out

- [ ] `plans/060/todo.md` Phase 0 checkboxes (Wave A) checked off.
- [ ] This file's checkboxes checked off.
- [ ] No Wave B–E checkbox touched; plan 060 not marked DONE anywhere.
- [ ] `git diff --stat` in each repo shows only in-scope files (see spec.md
      "Scope").
