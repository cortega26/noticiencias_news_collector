# Plan 060 / Phase 4b todo: Safe source-catalog mutation and batched listing

Execution index for [`spec.md`](spec.md). **spec.md is binding; do not
implement from this checklist alone.** Independent of phase-4a — do not
block on it, but check phase-4a's actual migration state before resolving
the reconciliation-marker STOP condition (spec.md Design §1 step 7).

## Step 0 — baseline

- [x] `make test` and `make type` pass on `main` before any change.
      (`make test`: 3167 passed; `make type`: green except 4 e2e_pipeline
      failures caused by a stale frontend `dist/` — environment, fixed by
      rebuilding the sibling checkout before proceeding.)
- [x] Re-read `news_collector/config/sources.py`'s `save_sources`/
      `validate_sources` and `serving/api.py`'s four source-mutation
      routes fresh — confirm spec.md's recon still matches current code
      before touching anything.

## Step 1 — `SourceCatalogWorkflow` (spec.md Design §1)

- [x] New file `news_collector/logic/workflows/source_catalog_workflow.py`.
- [x] `mutate()`'s full sequence (lock → fresh read → apply mutation →
      validate → atomic write → DB sync → compensate-on-failure → release)
      implemented exactly as spec.md describes, including the dedicated
      `.lock` file (not locking the YAML file being replaced) and the
      bounded-wait "catalog locked" typed result on timeout.
- [x] Resolve spec.md's STOP conditions before implementing step 4
      (`validate_sources()` signature fit) and step 7 (reconciliation
      marker's home) — check phase-4a's actual state for the latter.
- [x] `load()` read-only wrapper implemented.

## Step 2 — HTTP layer (spec.md Design §2)

- [x] `admin_upsert_source`, `admin_delete_source` call `mutate()` with a
      per-route closure; `admin_toggle_source`/`admin_reset_source_circuit`
      stay repository-direct (DB-only, no catalog write — see spec
      implementation record). Response shapes preserved; new
      locked(409)/reconciliation(500) paths added.
- [x] `admin_list_sources` composes one `load()` + the pre-existing
      batched `get_all_circuit_states()` call (plan 110).

## Step 3 — `SourceRepository` batching (spec.md Design §3)

- [x] No new method: plan 110's `get_all_circuit_states()` already is the
      batched query the list route uses; proven equivalent to the per-source
      loop by a new regression test.

## Step 4 — document the assumption (spec.md Design §4)

- [x] Single-writer deployment assumption written into
      `docs/database_deployment.md` or `AGENTS.md` (whichever is the
      correct "active doc" per this repo's own convention) — not just in
      this plan file.

## Step 5 — tests (spec.md "Test impact")

- [x] `test_admin_delete_source_*` and `test_admin_upsert_source_*`
      rewritten to use an isolated temp YAML via `create_app(..., sources_yaml_path=...)`
      (the `api_client` fixture now isolates the catalog for every test);
      asserted behavior (defaults, merge-preserve, unknown-id 404,
      validation 422) unchanged.
- [x] New atomicity test for `sources.yaml`, mirroring
      `test_admin_prompts_save_is_atomic`.
- [x] New: lock contention (two racing `mutate` calls, one waits/times
      out, file never corrupts).
- [x] New: DB-sync failure → YAML restored.
- [x] New: restore failure → `reconciliation_required` surfaced, not
      dropped.
- [x] New: batched circuit-state lookup ≡ old per-source loop for the
      same inputs.
- [x] `make test` and `make type` green.

## Step 6 — close out

- [x] `plans/060/todo.md` Phase 4 line updated (source-catalog half done;
      Phase 4 fully done once this merges).
- [x] `plans/README.md` ledger updated.
- [x] This file fully checked off.
