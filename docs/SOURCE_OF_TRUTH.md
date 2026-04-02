# Backend Source Of Truth

Status: Active and binding  
Scope: `/home/carlos/VS_Code_Projects/noticiencias/noticiencias_news_collector`

## Purpose

This document defines the backend governance stack, the actual repo boundary with the frontend repo, and the current truths that other backend docs are allowed to build on.

It governs documentation authority. It does not override code-owned contracts for exact field shapes or workflow definitions.

## Reality Snapshot

Noticiencias currently spans two sibling repositories:

- backend/orchestration repo: `noticiencias_news_collector`
- frontend/site repo: `noticiencias`

This repo owns:

- ingestion
- enrichment
- scoring, validation, taxonomy, and editorial policy
- persistence and API serving
- Refinery UI and publication orchestration
- the mirrored frontend publication contract

This repo does not own:

- frontend route structure
- frontend SEO emission
- frontend render-time component boundaries
- final site deployment semantics after the frontend merge and deploy complete

## Code-Owned Authority

The following files are authoritative for the exact concern they implement:

1. `news_collector/contracts/*.py`
   - boundary shapes and contract definitions
2. `news_collector/contracts/adapters.py`
   - contract-side structural mapping
3. `news_collector/contracts/frontend_schema.py`
   - backend mirror of the frontend publication artifact
4. `news_collector/storage/database.py`
   - persisted publication state and canonical slug persistence behavior
5. `news_collector/logic/workflows/refinery_engine.py`
   - current publication workflow behavior and recovery order
6. `config.toml`, `news_collector/config/*`, `config/sources.*`
   - runtime and source configuration
7. `Makefile` and `.github/workflows/*.yml`
   - real validation and automation behavior

If prose disagrees with these files about a field name, workflow step, job name, or command, the code wins and the documentation must be corrected.

## Documentation Authority

For backend governance and contributor behavior, authority is:

1. `docs/SOURCE_OF_TRUTH.md`
2. `docs/AGENTS.md`
3. `docs/ARCHITECTURE.md`
4. `docs/PIPELINE_CONTRACTS.md`
5. `docs/ci.md`
6. `docs/runbook.md`, `docs/collector_runbook.md`, `docs/operations.md`, `docs/testing.md`
7. `context/INVARIANTS.md`, `context/CONTRACTS.md`
8. `README.md`

`context/*` files are derived summaries for context efficiency. They should not introduce stronger law than the higher documents above.

## Current Non-Negotiable Truths

### Typed boundaries are the norm

Cross-subsystem boundaries are expected to use typed contracts from `news_collector/contracts/`. Local dict handling is acceptable during early parsing, but the normalized boundary shape should not remain a free-form dict.

### Adapters remain the structural conversion choke point

Mapping between ORM objects, raw export payloads, and contract models belongs in adapter code under `news_collector/contracts/`, not in `system/`, `serving/`, or UI code.

### The backend and frontend are separate systems

The backend may publish into the frontend repo, but the frontend remains authoritative for:

- `src/content/config.ts`
- `src/config.yaml`
- frontend route pathnames
- metadata emission

Any change to the publication frontmatter contract is a cross-repo change.

### Publication state semantics are bounded

This repo currently records `PR_CREATED` after pull-request creation. Final public website publication happens outside this repo after the frontend merge/deploy path completes.

### Identity reuse is real, absolute determinism is not yet universal

Current publication identity reuse order is:

1. persisted canonical slug in the database
2. existing frontend file or `refinery_manifest.json` recovery
3. new slug derived from source `published_date`
4. fallback to `collected_date`
5. last-resort fallback to current date

The current-date fallback is compatibility debt, not a desired long-term invariant.

## Non-Authoritative Material

The following are useful but not architectural authority:

- `audit/**`
- most report files under `docs/audits/**`
- archived refactor notes and one-off remediation plans
- `docs/ops/RUNBOOK.md`, which is now a legacy compatibility path pointing to the current runbooks
