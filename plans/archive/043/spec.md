# Plan 043: Repair active documentation — spec

## Outcome: DONE (Steps 1-4 complete; archived)

Steps 1-2 (code-derived truth matrix, end-to-end narrative correction) were
done and verified in the first pass. Steps 3-4 (expand doc drift from paths
to declared invariants; declare historical boundaries and ownership) were
completed in the second pass once plan 041 landed (`make verify-ci` +
`docs-check` wiring), per the ledger.

## Second pass (Steps 3-4) — what was in scope

1. **Step 3 (drift checker expansion)** — frontend `check-doc-drift.js` now
   validates the complete active-doc allowlist (13 docs), declared
   invariants parsed from authoritative files (schema path, site host,
   framework/runtime majors), and cross-repo references when the sibling
   checkout is present. The backend gained `scripts/check_doc_drift.py` +
   `make docs-check` (wired into `verify-ci`) covering paths, `make`
   targets, workflow filenames, Python major, and cross-repo refs.
2. **Step 4 (historical boundaries and ownership)** — both repos' doc
   indexes/SOURCE_OF_TRUTH declare historical scopes and fact ownership;
   both AGENTS.md review checklists require "docs follow code"; the backend
   gained `scripts/check_doc_review.py` (`make docs-review`), a changed-file
   gate that fails protected-path changes without an active-doc review and
   exempts archive/plans-only edits.

## Goals achieved in the second pass (each verified)

1. **Frontend checker covers the active allowlist** — 13 docs checked
   (previously 5): `README.md`, `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`,
   `docs/ARCHITECTURE.md`, `docs/SOURCE_OF_TRUTH.md`, `docs/tagging.md`,
   `docs/webhook-integration.md`, `docs/report-pipeline-setup.md`,
   `docs/supported-dependency-matrix.md`, `docs/DEPLOYMENT_SECURITY_HEADERS.md`,
   `docs/EDITORIAL.md`, `docs/EDITORIAL_VOICE.md`.
2. **Declared invariants fail with file/line/expected value** — the new
   stale classes each have a fixture and a test: stale schema path
   (`src/content/config.ts` -> `src/content.config.ts`), stale site host
   (`noticiencias.cl` -> host parsed from `src/config.yaml`/`astro.config.mjs`),
   stale `static Astro N site` (vs package.json major), stale `Node N`
   (vs engines major). Frontend tests: 11 green.
3. **Cross-repo references validated when sibling exists** — `DOC_DRIFT_SIBLING_ROOT`
   override for tests; sibling-absent mode skips silently. Fixtures + tests for
   both resolve and missing-file cases.
4. **Checker found and the pass fixed real drift** — frontend: `CLAUDE.md:18`
   claimed "Astro 6" (installed 7), `CONTRIBUTING.md:69` referenced the
   pre-split `src/content/config.ts`, `docs/tagging.md` used bare yml names
   for backend taxonomy files, `docs/EDITORIAL_VOICE.md` used shorthand
   `ds/atoms/Button.astro`, `docs/report-pipeline-setup.md` refs needed the
   `workers/` root prefix. Backend: `docs/database_deployment.md:15`
   referenced nonexistent `config/settings.py` (real module:
   `noticiencias/config_manager.py`).
5. **Backend equivalent green** — `make docs-check` validates 14 active docs
   (paths, `make` targets, workflow files, Python major, cross-repo refs).
   Backend pytest: 12 green.
6. **Changed-file gate** — `scripts/check_doc_review.py` (`make docs-review`)
   fails contract/config/workflow/serving/storage changes without an
   active-doc change; archive/plans-only edits pass. Backend pytest: 9 green.
7. **Historical boundaries declared** — `docs/INDEX.md`, both
   `docs/SOURCE_OF_TRUTH.md` files label audits/archive/migration/logs/ADR as
   historical evidence (no bulk edits); both `AGENTS.md` review checklists
   gained the "Docs follow code" item.
8. **`docs/ci.md` matches the gate** — `verify-ci` now includes `docs-check`.

## Verification (second pass)

- [x] Frontend `npm run check:doc-drift` -> exit 0, 13 docs.
- [x] Frontend `npx vitest run tests/check-doc-drift.test.ts` -> 11 passed.
- [x] Backend `make docs-check` -> exit 0, 14 docs.
- [x] Backend `pytest tests/unit/docs/test_check_doc_drift.py` -> 12 passed.
- [x] Backend `pytest tests/unit/docs/test_check_doc_review.py` -> 9 passed.
- [x] `make plans-ledger-check` -> OK.
- [x] OLLAMA_MODEL finding (#246): `.env:4` now `qwen3-next:80b-a3b-instruct-q4_K_M`
      (installed locally; matches `config.toml [ollama]` and the schema
      default); live resolution shows `auditor`/`default` from ENV resolving
      to that model with no normalization. Ledger updated to resolved.

## What was NOT done

- Frontend changed-file gate: the checklist requirement lives in frontend
  `AGENTS.md` §8 and is enforced by the backend gate for cross-repo contract
  changes; the frontend CI (content-guard) runs the drift check on every push.
- No bulk edits to historical docs; stale-string matches in
  `docs/adr/0003-content-schema-contract.md` and `docs/logs/MIGRATION_LOG.md`
  are intentional historical references (excluded by the plan's scope).

## What was in scope for this pass

Per the plan's Steps 1-2, cross-repo active documentation repair:

1. **Step 1 (truth matrix)** — done: every stale claim below was mapped
   to its code/config source and corrected file.
2. **Step 2 (correct the end-to-end system narrative)** — done: the
   stale strings are gone from active docs and the corrected paths/
   versions/domains are in place (verified below).
3. Steps 3-4 — deferred pending plan 041 full completion (the drift
   checker expansion builds on plan 041's `make verify-ci`/`verify:ci`
   entrypoints, which are PARTIAL).

## Goals actually achieved (each ledger claim verified against current files)

1. **Stale-string check clean** — the plan's stale-string command
   (`src/content/config\.ts`, `static Astro 5`, `audit-security\.yml`,
   `.github/workflows/security\.yml`, `noticiencias\.cl/post`) has **no
   active matches** in backend `README.md`/`docs/` or frontend
   `README.md`/`docs/` outside the excluded historical scopes
   (archive/audits/migration). The only remaining matches are in
   frontend `docs/adr/0003-content-schema-contract.md` (3×) and
   `docs/logs/MIGRATION_LOG.md` (1×) — both dated historical decision/
   migration records, which the plan's own scope section excludes
   ("archives, dated audits, changelogs, migration logs"). This matches
   the ledger's "no active matches" claim; the historical-file matches
   are intentional references to the pre-split schema path.
2. **Frontend README → Astro 7** — `../noticiencias/README.md:9` states
   "static Astro 7 site"; frontend commit `c85ac66` changed
   `README.md` as part of plan 043.
3. **`docs/tagging.md` path fixed** — frontend `docs/tagging.md:21` and
   `:98` reference `src/content.config.ts` (the post-split schema path),
   not `src/content/config.ts`; changed in `c85ac66`.
4. **`docs/ARCHITECTURE.md` search flow updated for plan 039** —
   frontend `docs/ARCHITECTURE.md:49-54` describes the build-time
   serialized Lunr index (`src/pages/search.json.js` +
   `src/utils/build-search-index.ts`, plan 039), not client-built search;
   changed in `c85ac66`.
5. **`docs/SOURCE_OF_TRUTH.md` search flow updated for plan 039** —
   frontend `docs/SOURCE_OF_TRUTH.md:90` names the build-time serialized
   Lunr index and plan 039; changed in `c85ac66`.
6. **Backend `docs/PRODUCT_FLOW.md` domain fixed** — backend
   `docs/PRODUCT_FLOW.md:62` and `:165` use `noticiencias.com`, not
   `noticiencias.cl`; backend commit `f95c6e2` ("docs: fix stale
   noticiencias.cl/post URL in PRODUCT_FLOW (plan 043)").
7. **Frontend drift checker still green** — `npm run check:doc-drift`
   (frontend) exits 0: "OK — 5 docs checked, all paths and commands
   verified."

## What was NOT done

- Step 3 (drift checker expansion from path existence to declared
  invariants: versions, workflow names, schema paths, site host) —
  deferred.
- Step 4 (declaring historical boundaries and owners; doc-review
  checklist on contract/workflow changes) — deferred.
- No backend README/`docs/security.md`/`docs/ci.md` narrative rewrites
  were part of this pass beyond the `PRODUCT_FLOW.md` domain fix; the
  ledger claims only what is verified above.

## Verification

- [x] Backend: `rg` stale-string pattern over `README.md docs` →
      zero active matches (only historical ADR/migration-log files
      remain, per plan's out-of-scope).
- [x] Frontend: `rg` stale-string pattern over `README.md docs` →
      zero active matches outside `docs/adr/0003` and
      `docs/logs/MIGRATION_LOG.md` (historical scope).
- [x] `../noticiencias/README.md:9` → Astro 7 (verified by read).
- [x] `../noticiencias/docs/tagging.md:21,98` → `src/content.config.ts`
      (verified by read).
- [x] `../noticiencias/docs/ARCHITECTURE.md:49-54` → plan 039 search
      flow (verified by read).
- [x] `../noticiencias/docs/SOURCE_OF_TRUTH.md:90` → plan 039 search
      flow (verified by read).
- [x] `docs/PRODUCT_FLOW.md:62,165` → `noticiencias.com` (verified by
      read).
- [x] `npm run check:doc-drift` (frontend) → exit 0.
