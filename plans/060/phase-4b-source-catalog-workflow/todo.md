# Plan 060 / Phase 4b todo: Safe source-catalog mutation and batched listing

Execution index for [`spec.md`](spec.md). **spec.md is binding; do not
implement from this checklist alone.** Independent of phase-4a — do not
block on it, but check phase-4a's actual migration state before resolving
the reconciliation-marker STOP condition (spec.md Design §1 step 7).

## Step 0 — baseline

- [ ] `make test` and `make type` pass on `main` before any change.
- [ ] Re-read `news_collector/config/sources.py`'s `save_sources`/
      `validate_sources` and `serving/api.py`'s four source-mutation
      routes fresh — confirm spec.md's recon still matches current code
      before touching anything.

## Step 1 — `SourceCatalogWorkflow` (spec.md Design §1)

- [ ] New file `news_collector/logic/workflows/source_catalog_workflow.py`.
- [ ] `mutate()`'s full sequence (lock → fresh read → apply mutation →
      validate → atomic write → DB sync → compensate-on-failure → release)
      implemented exactly as spec.md describes, including the dedicated
      `.lock` file (not locking the YAML file being replaced) and the
      bounded-wait "catalog locked" typed result on timeout.
- [ ] Resolve spec.md's STOP conditions before implementing step 4
      (`validate_sources()` signature fit) and step 7 (reconciliation
      marker's home) — check phase-4a's actual state for the latter.
- [ ] `load()` read-only wrapper implemented.

## Step 2 — HTTP layer (spec.md Design §2)

- [ ] `admin_upsert_source`, `admin_delete_source`, `admin_toggle_source`,
      `admin_reset_source_circuit` call `mutate()` with a per-route
      closure; existing response shapes/status codes preserved except the
      new locked/reconciliation-required paths.
- [ ] `admin_list_sources` composes one `load()` + one batched
      circuit-state call.

## Step 3 — `SourceRepository` batching (spec.md Design §3)

- [ ] `get_source_circuit_states(source_ids)` added — one `WHERE id IN
      (...)` query. Existing single-id method untouched.

## Step 4 — document the assumption (spec.md Design §4)

- [ ] Single-writer deployment assumption written into
      `docs/database_deployment.md` or `AGENTS.md` (whichever is the
      correct "active doc" per this repo's own convention) — not just in
      this plan file.

## Step 5 — tests (spec.md "Test impact")

- [ ] `test_admin_delete_source_*` and `test_admin_upsert_source_*`
      updated to patch the workflow/YAML path instead of module globals;
      asserted behavior (defaults, merge-preserve, unknown-id 404,
      validation 422) unchanged.
- [ ] New atomicity test for `sources.yaml`, mirroring
      `test_admin_prompts_save_is_atomic`.
- [ ] New: lock contention (two racing `mutate` calls, one waits/times
      out, file never corrupts).
- [ ] New: DB-sync failure → YAML restored.
- [ ] New: restore failure → `reconciliation_required` surfaced, not
      dropped.
- [ ] New: batched circuit-state lookup ≡ old per-source loop for the
      same inputs.
- [ ] `make test` and `make type` green.

## Step 6 — close out

- [ ] `plans/060/todo.md` Phase 4 line updated (source-catalog half done;
      check off Phase 4 entirely once both 4a and 4b are merged).
- [ ] `plans/README.md` ledger updated.
- [ ] This file fully checked off.
