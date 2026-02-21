# CONTRACTS.md — Boundary & Contract Registry

## Authority

- SOURCE_OF_TRUTH.md overrides all
- docs/AGENTS.md is binding unless it conflicts with SOURCE_OF_TRUTH.md
- This file is a registry derived from those authorities and the codebase

## Sealed Boundaries

| Boundary   | Method / Entry Point     | Contract                             | Adapter                                                                          | Notes                              | Verification           |
| :--------- | :----------------------- | :----------------------------------- | :------------------------------------------------------------------------------- | :--------------------------------- | :--------------------- |
| Validation | `_execute_validation`    | `ArticleValidationPayload`           | `news_collector/contracts/adapters.py` (function: `adapt_to_validation_payload`) | Pydantic schema validation         | `make test-boundaries` |
| Scoring    | `_execute_scoring`       | `ScoringInputModel`                  | `news_collector/contracts/adapters.py` (function: `adapt_to_scoring_input`)      | Pydantic schema validation         | `make test-boundaries` |
| Export     | `export_latest_articles` | Unverified: ExportContractV1 missing | `news_collector/contracts/adapters.py` (function: `adapt_article_to_export`)     | `ExportContractV2` present instead | `make test-boundaries` |

## Adapter Rules Summary

- Adapters are the absolute exclusive conversion layer.
- All data crossing any system boundary MUST be encapsulated in Pydantic models.
- Passing raw dictionaries across system boundaries is strictly forbidden.
- Creating ad-hoc schemas inline is prohibited.
- Mutating payloads after validation is strictly forbidden.
- System orchestration code (`news_collector/system/`) may never construct payloads.
- Adapters SHOULD be side-effect minimal and avoid I/O; conversion remains their primary responsibility.

## Commands

- make test-contracts
- make test-boundaries
- make test-system
