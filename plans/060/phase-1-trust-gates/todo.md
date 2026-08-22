# Plan 060 / Phase 1 todo: Close low-cost security, CI, dashboard, and docs gaps

Execution index for [`spec.md`](spec.md). The spec's excerpts, exact
replacement text, scope boundaries, STOP conditions, and done criteria are
binding; do not implement from this checklist alone.

## Step 0 — baseline

- [ ] Backend `make docs-check`, `make plans-ledger-check`,
      `pytest tests/unit/docs/test_check_doc_drift.py -v` pass on an
      unmodified checkout.
- [ ] Frontend `npm run lint`, `npm run check:doc-drift`, strict
      snapshot contract-sync pass on an unmodified checkout.

## Step 1 — backend: Gitleaks checksum verification

- [ ] `.github/workflows/quality.yml` Install-Gitleaks step rewritten:
      download to temp dir, verify against `checksums.txt` via
      `sha256sum -c`, extract only after verification, install to
      `$RUNNER_TEMP/bin` + `$GITHUB_PATH`.
- [ ] `scripts/verify_gitleaks_checksum_test.sh` added, proves tamper
      detection works, exits 0 and prints `PASS`.
- [ ] Workflow YAML re-parses cleanly (`yaml.safe_load`).

## Step 2 — backend: stale publication-date docs + invariant (one commit)

- [ ] `docs/PIPELINE_CONTRACTS.md` "Current Identity Reuse Order" section
      replaced with the exact text in spec.md.
- [ ] `docs/ARCHITECTURE.md` line 151 replaced with the exact text in
      spec.md.
- [ ] Two new `stale_publication_date_fallback` checks added to
      `check_invariants()` in `scripts/check_doc_drift.py`.
- [ ] `tests/fixtures/doc-drift/stale/README.md` has a new line with
      `current date as last resort`.
- [ ] `test_flags_stale_publication_date_fallback` added to
      `tests/unit/docs/test_check_doc_drift.py`.
- [ ] All of the above landed in a single commit (not split across the
      invariant-add and the doc-fix).
- [ ] `pytest tests/unit/docs/test_check_doc_drift.py -v` fully green,
      including `test_live_repo_docs_pass`.

## Step 3 — frontend: wire `check:search-budget`

- [ ] `package.json`: `check:search-budget` script added.
- [ ] `content-guard.yml`: new "📏 Search Budget" step after "🧪 Dist Sanity".
- [ ] `package.json`: `verify:ci` gains `check:search-budget` after
      `test:dist`.
- [ ] `tests/check-search-budget.test.ts` added: passing-fixture case and
      oversized-fixture case (built with many entries to trip the gzip
      ceiling specifically, not the bloat heuristic); oversized case
      asserts on the specific `exceeds ... ceiling` message.
- [ ] `npm run build && npm run check:search-budget` passes end-to-end.

## Step 4 — frontend: `check:contract-sync` strict everywhere

- [ ] `package.json`: `--strict` added to `check:contract-sync`.
- [ ] `content-guard.yml`: `--strict` added to the snapshot-mode fallback
      invocation.
- [ ] `.github/workflows/sync-contract-snapshot.yml` checked — confirmed
      no non-strict `--strict`-eligible invocation needs fixing (or fixed,
      if one was found).
- [ ] Both live and snapshot strict checks verified passing.

## Step 5 — frontend: dashboard + `CONTRIBUTING.md`

- [ ] `src/pages/admin/dashboard.astro:106` ("Imágenes hero") →
      `'unknown' as const`, detail string updated.
- [ ] `src/pages/admin/dashboard.astro:118` ("Linting") →
      `'unknown' as const`, detail string updated.
- [ ] `CONTRIBUTING.md:22` build-command comment corrected.
- [ ] `CONTRIBUTING.md:29-33` `verify:ci`/CI-parity claim corrected to an
      honest, bounded description (applied after Step 3's `verify:ci`
      change).
- [ ] `npm run lint` passes (confirms the status-literal change type-checks).

## Verified current — no fix needed (do not re-search)

- [x] Node 24 claims across active docs and CI workflows — checked, current.
- [x] `src/content/config.ts` stale schema-path — checked, zero occurrences,
      existing invariant already guards it.
- [x] Image-delivery-mode claims — checked, nothing stale.
- [x] "Legacy fallback" language — checked, nothing stale.

## Step 6 — close out

- [ ] `plans/060/todo.md` Phase-1 checkboxes (Wave A) checked off.
- [ ] This file fully checked off.
- [ ] No other wave's checkboxes touched; plan 060 not marked DONE anywhere.
- [ ] `git diff --stat` in each repo shows only in-scope files (see spec.md
      "Scope").
