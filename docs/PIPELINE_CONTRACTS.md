# Pipeline Contracts

Status: Active  
Authority: Subordinate to `docs/SOURCE_OF_TRUTH.md`, `docs/AGENTS.md`, and `docs/ARCHITECTURE.md`

## Purpose

This document records the contract-bearing flows that matter operationally today: what artifact crosses a boundary, who owns it, and what failure behavior exists in code now.

It intentionally distinguishes current behavior from desired future hardening.

## Contract Inventory

| Flow | Producer | Consumer | Contract / Artifact | Current behavior |
| --- | --- | --- | --- | --- |
| Collection export | `news_collector/system/reporting.py` and collector entrypoints | `apps/refinery/main.py` | `ExportContractV2` from `news_collector/contracts/export.py` | `schema_version: 2` is the preferred path; legacy `schema_version: 1` is still tolerated with warnings |
| Scoring boundary | workflow/system code | scoring modules | `ArticleScoringData`, `ScoringInputModel` | adapter-owned mapping in `news_collector/contracts/adapters.py` |
| Validation boundary | workflow/system code | validation modules | `ArticleValidationPayload` | adapter-owned mapping in `news_collector/contracts/adapters.py` |
| Frontend publication artifact | `news_collector/logic/workflows/refinery_engine.py` | sibling frontend repo | frontmatter/body matching `AstroPost` mirror in `news_collector/contracts/frontend_schema.py` | cross-repo mirror of `../noticiencias/src/content.config.ts` |
| Read API | `news_collector/serving/api.py` | HTTP clients | `ArticleListParams`, `ArticlesEnvelope` | deterministic cursor pagination and validated query parameters |

## Export To Refinery

### Preferred Contract

- top-level export shape: `ExportContractV2`
- article shape: `ExportArticleModel`

### Current Compatibility

- `apps/refinery/main.py` still supports legacy export payloads and missing/invalid `schema_version` through compatibility handling
- this is real compatibility surface, not a theoretical note

### Current Failure Semantics

- invalid or missing export artifacts do not necessarily stop all Refinery usage
- Refinery code contains fallback paths, including database-backed candidate loading in the UI path
- those fallback paths reduce operator dead-ends, but they also mean the export artifact is not the only current ingress path

## Frontend Publication Contract

### Authoritative Shape

The backend mirror is:

- `news_collector/contracts/frontend_schema.py`

The render authority is:

- `../noticiencias/src/content.config.ts`

### Current Publication Path

- output directory: `src/content/posts/` in the target frontend repo
- file naming: `<canonical-slug>.md`
- sidecar manifest: `refinery_manifest.json`
- category resolution reads top-level export `category` first, then falls back to `metadata.category`
- refinery-generated posts must publish exactly one primary category from the current editorial taxonomy
- `Editorial` is reserved for first-party Noticiencias-authored pieces; translated third-party articles must resolve to a non-`Editorial` category

### Current Identity Reuse Order

`RefineryEngine` currently resolves publication identity in this order:

1. database `canonical_slug`
2. existing frontend file or sidecar manifest
3. `published_date`
4. `collected_date`
5. current date as last resort

The final two fallback steps are compatibility debt. They are not the desired end state for immutable identity.

### Publication State Semantics

- PR creation updates backend state to `PR_CREATED`
- optional auditor execution happens after PR creation
- final frontend site publication occurs after merge and frontend deploy, outside this repo

## API Contract

The serving layer currently exposes a read-oriented API:

- validated request parameters via `ArticleListParams`
- deterministic cursor encoding using score, collected timestamp, and article ID
- envelope response shape via `ArticlesEnvelope`

The serving layer is not the owner of editorial mutation workflows.

## Current Gaps To Treat As Gaps

- The backend's own parity test (`tests/test_contracts_sync.py`) covers only top-level field names; the full type/constraint/optionality comparison is enforced by the frontend's checker, which backend CI runs in strict mode (`.github/workflows/ci.yml` → `contract-parity` job) and the frontend runs on every push (Content Guard).
- Frontend validation-failure notifications (`POST /api/v1/webhook/frontend`, `serving/api.py`) depend on `BACKEND_WEBHOOK_URL`/`BACKEND_WEBHOOK_TOKEN` being configured in the frontend repository — they must be set for the failure loop to close.
- Publication identity reuse is strong but still has fallback branches that can use non-source dates.
- `RefineryEngine` remains broader than ideal and mixes several responsibilities inside one workflow module.
