# INVARIANTS.md — Backend Derived Invariants

Status: Derived summary
Authority: Subordinate to `docs/SOURCE_OF_TRUTH.md`, `docs/AGENTS.md`, and `docs/ARCHITECTURE.md`

## Purpose

This file is a compact invariant summary for backend contributors and agents. It should mirror higher-authority docs and code reality without inventing stronger guarantees.

## Current Invariants

### I-1: Boundary contracts stay typed

Sealed subsystem boundaries are expected to use models from `news_collector/contracts/` rather than free-form dicts that leak across packages.

### I-2: Adapters own structural mapping

Cross-boundary conversion between raw/export/ORM shapes and contract shapes belongs in adapter code under `news_collector/contracts/`.

### I-3: `system/` coordinates

`news_collector/system/` is the orchestration layer. Policy, editorial judgment, and contract-shaping logic should not spread there.

### I-4: Publication identity is reused before it is regenerated

Current publication identity resolution order is:

1. stored database slug
2. existing frontend file or `refinery_manifest.json`
3. source `published_date`, then `collected_date`
4. quarantine with `UndatedArticleError` (`E_IDENTITY_NO_DATE`) if neither exists

There is no runtime-clock fallback. Reuse persisted identity before deriving a new slug.

### I-5: Frontend publication is a cross-repo contract

`news_collector/contracts/frontend_schema.py` mirrors the frontend render contract in `../noticiencias/src/content.config.ts`. Either side changing that shape is a cross-repo contract event.

### I-6: Publication stages and acknowledgments remain distinct

PR creation records `PR_CREATED`; authenticated frontend callbacks can complete
or reject matching publication attempts. Empty `publication_ids` do not trigger
article guessing. Workflow success and scoring `completed` are not proof that a
public URL is live. Frontend CI owns merge/build/deployment behavior.

### I-7: Context files are summaries, not constitutions

`context/*` files help with efficient codebase reasoning. If they conflict with higher docs or code, the higher docs and code win.

### I-8: Workflow recovery preserves active ownership

Collection and publication each allow one queued/running run. Dispatch-time
recovery interrupts expired running leases and preserves queued rows; startup
also recovers queued rows under the single-owner startup assumption. A missing
heartbeat is stale only after `started_at` exceeds the lease age. Terminal rows
stay terminal. See the two run workflows and their unit tests for exact guards.
