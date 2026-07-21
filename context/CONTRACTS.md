# CONTRACTS.md — Boundary Registry

> NON-AUTHORITATIVE DOCUMENT
> This file is a derived registry for reference purposes only.
> If a conflict exists, `docs/AGENTS.md` and `docs/SOURCE_OF_TRUTH.md` prevail.
> This file does not introduce new law; it summarizes active code and higher-authority docs.

## Authority

- `docs/SOURCE_OF_TRUTH.md` defines the documentation hierarchy
- `docs/AGENTS.md` defines binding backend change law
- `docs/ARCHITECTURE.md` and `docs/PIPELINE_CONTRACTS.md` explain current implementation and flow
- this file is a lookup aid derived from those sources and the codebase

## Sealed Or Important Boundaries

| Boundary | Entry point | Contract / artifact | Code owner | Verification |
| --- | --- | --- | --- | --- |
| Validation payload | workflow/system into validation | `ArticleValidationPayload` | `news_collector/contracts/validation.py` plus `news_collector/contracts/adapters.py` | `make test-boundaries` |
| Scoring payload | workflow/system into scoring | `ScoringInputModel` | `news_collector/contracts/scoring.py` plus `news_collector/contracts/adapters.py` | `make test-boundaries` |
| Export artifact | collector/reporting into Refinery | `ExportContractV2` | `news_collector/contracts/export.py` | export tests and Refinery payload tests |
| Frontend publication mirror | publication workflow into sibling frontend repo | `AstroPost` mirror | `news_collector/contracts/frontend_schema.py` | `tests/test_contracts_sync.py`, `tests/unit/contracts/test_frontend_schema.py` |
| Read API query boundary | HTTP requests into serving layer | `ArticleListParams` and `ArticlesEnvelope` | `news_collector/serving/api.py` | serving API tests |

## Derived Notes

- Adapter-owned conversion remains the current pattern described by `docs/AGENTS.md`.
- Export compatibility still includes legacy payload handling in Refinery code.
- The frontend publication mirror summarizes the frontend schema but does not replace `../noticiencias/src/content.config.ts`.

## Commands

- `make test-contracts`
- `make test-boundaries`
- `make test-system`
