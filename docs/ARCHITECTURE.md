# Backend Architecture

Status: Active and binding  
Authority: Subordinate to `docs/SOURCE_OF_TRUTH.md` and `docs/AGENTS.md`

## Purpose

This document describes the backend architecture as it exists today: package ownership, dependency direction, flow of data, and the boundaries that contributors should preserve.

It is not a target-state manifesto.

## System Map

### Boundary And Integration Layer

- `news_collector/contracts/`
  - Pydantic models and adapter functions for export, scoring, validation, frontend publication, system payloads, and image briefs
- `news_collector/serving/`
  - FastAPI read surface
- `apps/refinery/`
  - Streamlit UI and local published-content inspection helpers

### Ingestion And External I/O

- `news_collector/collectors/`
- `news_collector/enrichment/`
- `news_collector/infrastructure/`

These packages own network I/O, provider integration, feed parsing, and external-service interaction.

### Policy And Decision Logic

- `news_collector/scoring/`
- `news_collector/validation/`
- `news_collector/taxonomy/`
- `news_collector/editorial/`
- `news_collector/reranker/`
- `news_collector/components/editorial/`

These packages own rules, heuristics, editorial decisions, and decision-support behavior.

### Orchestration And Workflows

- `news_collector/system/`
- `news_collector/logic/workflows/`
- `news_collector/components/publishing/`

These packages coordinate flow, retries, publication steps, reporting, and GitHub-facing publication actions.

### Persistence And Support Layers

- `news_collector/storage/`
- `news_collector/monitoring/`
- `news_collector/observability/`
- `news_collector/perf/`
- `news_collector/utils/`

## Dependency Direction

Preferred dependency direction is inward toward contracts, policy, and persistence boundaries:

- ingestion and UI edges depend inward
- orchestration composes collaborators
- storage owns database concerns
- policy modules stay runnable without network or UI state when possible
- contracts define stable shapes at subsystem boundaries

Specific rules:

- `system/` should coordinate, not author business rules
- `contracts/` should validate and map, not perform I/O
- `storage/` should own writes and DB-specific behavior
- `serving/` should stay read-oriented
- `apps/refinery/` should not become an alternate contract-definition layer

## Current End-To-End Flow

### Collection And Storage

1. `scripts/run_collector.py` bootstraps the system.
2. collectors fetch source content and normalize raw payloads.
3. contracts validate ingress shapes where boundaries are sealed.
4. storage persists candidate articles.
5. reporting/export surfaces produce ranked/exportable payloads.

### Refinery And Publication

1. `apps/refinery/main.py` loads export artifacts and supports legacy payload handling.
2. `news_collector/logic/workflows/refinery_engine.py` coordinates editorial processing, image handling, policy checks, file writing, manifest updates, Git operations, and PR creation.
3. Publication targets the sibling frontend repo path `src/content/posts/`.
4. After PR creation, the backend records publication state as `PR_CREATED`.
5. Optional auditor work runs after PR creation and records audit metadata without changing site publication state.

### API Serving

1. `news_collector/serving/api.py` exposes read-oriented ranked article endpoints.
2. Query parameters are validated with Pydantic models.
3. Pagination is cursor-based and deterministic by score, collected timestamp, and ID.

## Contract Boundaries That Matter Most

- export artifact consumed by Refinery: `news_collector/contracts/export.py`
- scoring boundary: `news_collector/contracts/scoring.py`
- validation boundary: `news_collector/contracts/validation.py`
- frontend publication mirror: `news_collector/contracts/frontend_schema.py`
- raw/export-to-contract mapping: `news_collector/contracts/adapters.py`

## Current Technical Debt That The Docs Must Not Hide

### `RefineryEngine` is still too broad

`news_collector/logic/workflows/refinery_engine.py` currently bundles orchestration with:

- file I/O
- image download routing
- manifest management
- Git branch and PR work
- recovery logic

That is the current reality. Contributors should avoid making it broader and should prefer extracting narrower collaborators when touching adjacent functionality.

### Publication identity is strong but not perfect

The workflow reuses database or file-based identity when available, but it still falls back to `collected_date` and then current date when source dates are missing. Documentation should treat that as bounded compatibility debt, not as perfect determinism.

### Legacy entrypoints still exist

`main.py`, older workflows, and schema-version compatibility code remain in the repo. They are part of the current support surface and should be documented as legacy compatibility, not erased from the architecture narrative.

## Extension Rules

- New boundary payloads should land in `news_collector/contracts/`.
- New external integrations should stay in ingestion/infrastructure layers, not in `system/`.
- New editorial policy should live with editorial or policy modules, not in adapters or storage.
- New publication features should preserve the repo boundary: backend prepares artifacts and PRs; frontend owns render, routes, and deployment.
