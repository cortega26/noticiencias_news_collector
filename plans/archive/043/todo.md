# Plan 043: Repair active documentation — todo

Status: COMPLETE (Steps 1-4 all done). Ledger row updated to DONE; plan
archived. See `plans/043/spec.md` for the full outcome record.

## Steps 1-2 (previous pass, PARTIAL)

- [x] Step 1: code-derived truth matrix (stale claims mapped to code/config sources)
- [x] Step 2: correct the end-to-end system narrative (README, PRODUCT_FLOW, ARCHITECTURE, SOURCE_OF_TRUTH, tagging.md)

## Step 3 (this pass): expand doc drift from paths to declared invariants

- [x] Frontend `check-doc-drift.js`: expand allowlist to the complete active
      doc set (README, AGENTS, CLAUDE, CONTRIBUTING, ARCHITECTURE,
      SOURCE_OF_TRUTH, tagging, webhook-integration, report-pipeline-setup,
      supported-dependency-matrix, DEPLOYMENT_SECURITY_HEADERS, EDITORIAL,
      EDITORIAL_VOICE)
- [x] Frontend invariant classes: stale schema path `src/content/config.ts`
      (expected `src/content.config.ts`), stale site host `noticiencias.cl`
      (expected host parsed from `src/config.yaml`/`astro.config.mjs`), stale
      "static Astro N site" major (parsed from package.json dependencies),
      stale Node major (parsed from engines.node)
- [x] Frontend cross-repo references: `../noticiencias_news_collector/...`
      validated when the sibling checkout exists; skipped when absent
      (DOC_DRIFT_SIBLING_ROOT override for tests)
- [x] Frontend fixtures + tests for each stale class (`tests/fixtures/doc-drift/`
      `stale`, `sibling-ok`, `sibling-broken`; 11 tests green)
- [x] Repairs surfaced by the extended checker: CLAUDE.md "Astro 6" -> 7;
      CONTRIBUTING.md `src/content/config.ts` -> `src/content.config.ts`;
      tagging.md cross-repo yml paths; EDITORIAL_VOICE.md `ds/atoms/Button.astro`
      -> full path; report-pipeline-setup.md `workers/` prefix resolution
- [x] Backend `scripts/check_doc_drift.py`: mirrors the frontend checks plus
      `make <target>` existence against the Makefile, `.github/workflows/*.yml`
      existence, Python major from `.python-version`, cross-repo refs
- [x] Backend `make docs-check` target; wired into `verify-ci`; `docs/ci.md`
      updated to match
- [x] Backend fixtures + pytest suite (`tests/unit/docs/test_check_doc_drift.py`,
      12 tests green)
- [x] Backend repair surfaced: `docs/database_deployment.md` `config/settings.py`
      -> `noticiencias/config_manager.py`

## Step 4 (this pass): declare historical boundaries and ownership

- [x] Backend `docs/INDEX.md`: audit artifacts explicitly labeled historical;
      historical boundary rule added
- [x] Backend `docs/SOURCE_OF_TRUTH.md`: "Fact Ownership" table + "Historical
      Boundaries" section
- [x] Frontend `docs/SOURCE_OF_TRUTH.md`: same two additions
- [x] Backend `docs/AGENTS.md` section 9: "Docs follow code" checklist item
- [x] Frontend `AGENTS.md` section 8: same checklist item
- [x] Backend `scripts/check_doc_review.py` changed-file gate + `make docs-review`
      target (fails when contracts/config/workflow/serving/storage change
      without an active-doc change; archive/plans-only edits exempt)
- [x] Tests for the gate (`tests/unit/docs/test_check_doc_review.py`, 9 green)

## Verification

- [x] Frontend `npm run check:doc-drift` -> OK (13 active docs)
- [x] Frontend vitest `tests/check-doc-drift.test.ts` -> 11 passed
- [x] Backend `make docs-check` -> OK (14 active docs)
- [x] Backend pytest docs suites -> 12 + 9 passed
- [x] `make plans-ledger-check` -> OK
- [x] OLLAMA_MODEL finding (#246): resolved — `.env:4` =
      `qwen3-next:80b-a3b-instruct-q4_K_M`, installed locally, matches
      config.toml and schema default; resolved map verified end-to-end
