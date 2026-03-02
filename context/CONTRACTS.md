# CONTRACTS.md — Boundary & Contract Registry

> ⚠️ NON-AUTHORITATIVE DOCUMENT
> This file is a derived registry for reference purposes only.
> If any conflict exists, `docs/AGENTS.md` prevails.
> This document must NOT introduce or redefine architectural law (per `docs/AGENTS.md`).

## Authority

- SOURCE_OF_TRUTH.md overrides all
- docs/AGENTS.md is binding unless it conflicts with SOURCE_OF_TRUTH.md
- This file is a registry derived from those authorities and the codebase

## Sealed Boundaries

| Boundary   | Method / Entry Point     | Contract                             | Adapter                                                                          | Notes                              | Verification           |
| :--------- | :----------------------- | :----------------------------------- | :------------------------------------------------------------------------------- | :--------------------------------- | :--------------------- |
| Validation | `_execute_validation`    | `ArticleValidationPayload`           | `news_collector/contracts/adapters.py` (function: `adapt_to_validation_payload`) | Pydantic schema validation         | `make test-boundaries` |
| Scoring    | `_execute_scoring`       | `ScoringInputModel`                  | `news_collector/contracts/adapters.py` (function: `adapt_to_scoring_input`)      | Pydantic schema validation         | `make test-boundaries` |
| Export     | `export_latest_articles` | `ExportContractV2` (legacy v1 normalized at adapter boundary) | `news_collector/contracts/adapters.py` (functions: `adapt_article_to_export`, `adapt_export_article_to_collector_payload`) | Legacy `source_name -> source_id` fallback allowed only for schema_version `1` | `make test-boundaries` |

## Adapter Rules Summary

- Derived from `docs/AGENTS.md` LAW-1 and LAW-2:
- Adapters are the exclusive conversion layer.
- Cross-boundary payloads use Pydantic models.
- Raw dictionaries are not used for sealed boundary transfer.
- Inline ad-hoc schemas are not used at boundaries.
- Payload mutation after validation is avoided.
- System orchestration code does not construct boundary payloads.
- Adapters stay side-effect-light and avoid I/O where practical.

## SmartHttpClient URL Scheme Contract

- Only `http` and `https` schemas are allowed.
- Non-HTTP schemes (e.g., `ftp`, `file`, `gopher`, `smb`) are rejected.
- SSRF validation is performed through `validate_url_safety` before HTTP dispatch.

## Commands

- make test-contracts
- make test-boundaries
- make test-system
