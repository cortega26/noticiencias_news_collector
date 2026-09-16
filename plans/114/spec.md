# Plan 114: Series curation + transparency aggregates + search budget

> **Executor instructions**: Compounding work — series give retention, transparency aggregates give press/grant leverage, search-budget enforcement prevents a silent cliff. No schema changes. Update the `114` row in `plans/README.md` when complete.
>
> **Drift check (run first)**:
> Frontend `git diff --stat HEAD -- src/pages/series/ src/pages/transparencia.md src/utils/build-search-index.ts src/pages/search.json.js`; backend `git diff --stat HEAD -- data/article_metadata/ news_collector/monitoring/reporting.py`.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: None (107 numbers nice-to-have for transparency copy, not blocking); Wave 3 — parallel-safe with 113
- **Category**: growth/compounding
- **Planned at**: backend `9fa77b6`, 2026-09-16 (mostly frontend work in `../noticiencias`)

## Why this matters

Series routes exist but render "Próximamente" (zero posts carry `series:` frontmatter) — a dead end on the site. Rolling auditor averages sit in a local JSON file where only operators see them; published aggregates are a trust differentiator for grants/press. Lunr client-side search is fine at 36 posts and will silently degrade by ~500 — the budget check must define the migration trigger now.

## Current state (verified)

- FE `src/pages/series/index.astro:1-55 + [series].astro:1-56` (`index:true`); no `series:` frontmatter in the 36 posts → `seriesList.length==0` → placeholder copy.
- BE `data/article_metadata/auditor_rolling_average.json` (operator-local); FE `transparencia.md` exists; related-posts enabled (count 4).
- Search: `src/pages/search.json.js:1-68` (Lunr artifact via `buildSearchArtifact`; 400px images) → `utils/browser/search-index.ts:28 fetch('/search.json')` → `buscar.astro`; `scripts/check-search-budget.js` enforced in `verify:ci`.

## Scope

**In scope**: 3 starter series (curated from existing 36 posts via `series:` frontmatter on re-publish or series-index curation — whichever the frontend supports without a contract change; if frontmatter needs a schema addition it becomes a cross-repo contract change and must follow that gate); transparency section with anonymized aggregate auditor numbers (never per-article scores, never raw claims); documented Lunr→Pagefind trigger threshold + budget numbers.

**Out of scope**: new collection schema fields (unless gated as contract change), per-article score display, search migration implementation, paywall/premium series.

## Steps

### Step 1: Three starter series (frontend)
Curate 3 series from the existing corpus (e.g. methods-literacy, health-claims, space). Wire index + detail pages with real lists; remove the "Próximamente" dead end. If `series:` frontmatter is already supported by `content.config.ts`, use it; otherwise curate via the existing taxonomy without touching the schema.

**Verify**: series pages list real posts; `npm run validate:content + check:editorial-fields` green.

### Step 2: Transparency aggregates (frontend + backend numbers)
Publish anonymized rolling averages (epistemic rigor / clarity / speculation control / engagement) with methodology note and sample window. Numbers must match the backend aggregate file exactly at publish time; record the source commit/date in the plan close-out.

**Verify**: numbers match backend file; `npm run validate:content` green.

### Step 3: Search budget trigger (frontend)
Record current `search.json` size vs budget, define the numeric Lunr→Pagefind migration trigger, and ensure `check:search-budget` covers it. No migration code.

**Verify**: `npm run check:search-budget` green with trigger documented.

## Verification (full gate)

| Purpose | Command | Expected |
|---|---|---|
| Ledger (backend) | `.venv/bin/python scripts/validate_plans_ledger.py` | OK |
| Frontend | `npm run validate:content && npm run lint && npm run check:search-budget && npm run test:e2e` | exit 0 |

## STOP conditions

- STOP if series need a frontmatter schema addition — that is a cross-repo contract change (`frontend_schema.py` mirror + `check:contract-sync --strict` + both repos' suites); re-scope explicitly instead of sneaking it in.
- STOP if aggregates cannot be reproduced from the backend file — never hand-write trust numbers.

## Git workflow

- Branch (frontend): `advisor/114-series-transparency-search`.
- Commit example: `feat: starter series and transparency aggregates`.
