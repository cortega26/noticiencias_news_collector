# Plan 043: Repair active documentation — spec

## Outcome: PARTIAL (Steps 1-2 done; Steps 3-4 deferred)

Steps 1-2 (code-derived truth matrix, end-to-end narrative correction)
are done and verified below. Steps 3-4 (expand doc drift from paths to
declared invariants; declare historical boundaries and ownership) are
deferred pending plan 041 full completion, per the ledger.

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
