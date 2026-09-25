# Plan 060 todo: Cross-repository publication reliability and architecture hardening

This checklist is an execution index for [`spec.md`](spec.md). The spec's
decisions, STOP conditions, rollback rules, and acceptance criteria are binding;
do not implement from this checklist alone.

## Program controls

- [ ] Create a small implementation `spec.md` and `todo.md` for each phase.
- [ ] Run the phase drift check against backend `d63cbea` and frontend
      `237cd13`; update plan evidence if current code differs.
- [ ] Use S/M pull requests; keep both repositories deployable after every
      merge.
- [ ] Record tests actually executed and SHAs/PRs in the master execution
      record.
- [ ] Keep plan 048 independent and do not reopen rejected/completed work.

## Wave A — immediate trust gates

### Phase 0 — baseline and decisions

- [x] Add matching ADRs for durable state, generated contracts, and the
      harden-before-consolidating repository decision.
- [x] Add the versioned shared publication valid/invalid fixture corpus.
- [x] Add deterministic OpenAPI/publication schema snapshot commands.
- [x] Preserve the strict editorial failure inventory as migration input.
- [x] Verify snapshot generation twice with byte-identical output.

### Phase 1 — small security, CI, dashboard, and docs gaps

- [x] Pin and checksum-verify the Gitleaks download in backend CI.
- [x] Correct backend active publication-date docs and drift assertions.
- [x] Wire the frontend search budget into a fresh-build CI path and add pass/fail
      fixtures.
- [x] Make live and snapshot contract-sync commands strict.
- [x] Replace dashboard hard-coded passes with measured values or `unknown`.
- [x] Correct frontend Node/schema/image/build/CI/legacy-fallback active docs
      (build-command and CI-parity claims corrected; Node/schema/image/legacy-fallback
      were already current, verified not fixed).
- [x] Run each repository's applicable doc and CI gates.

## Wave B — correctness and durable orchestration

### Phase 2 — truthful schema v2

- [x] Characterize complete/empty/partial/invalid/cached/provider-failure v2
      assembly. (Phase 2a — orchestration-boundary and fixture-level
      characterization; assembly-level behavior itself was already
      characterized by pre-existing tests, see phase-2a-v2-failclosed/spec.md
      "Baseline correction".)
- [x] Fail incomplete new v2 output before writer/Git side effects with a stable
      retryable error code. (Phase 2a — this behavior already existed in
      production since commit `65e934a`, predating this plan's own baseline;
      Phase 2a added regression coverage, not the behavior itself.)
- [x] Replace the backend v1 smoke fixture with deterministic production-path v2.
      (Phase 2a.)
- [x] Inventory and human-review the corpus; invent no facts. Two AI audit
      rounds (August 2026) got this most of the way — see prior history
      below — but per spec.md an AI audit is evidence for the operator's
      review, not a substitute. **On 2026-09-14 the operator was asked
      directly and explicitly authorized the assistant to perform this
      review itself**, a recorded one-time policy override (see
      `phase-2b-corpus-cutover/review/step2-review-outcomes-2026-09-14.md`,
      "Policy note"). Under that authorization all 23 posts currently at
      `schema_version: 2` (corpus grew to 35 posts total since August)
      were independently re-verified from scratch against real sources:
      19/23 clean, 4/23 got minor metadata/body-reconciliation
      corrections (not factual retractions), 0 downgrades, 0 material
      errors. Prior history: Phase 2b Step 1 produced a machine-drafted
      inventory (30/30 posts drafted); round 1 (operator-commissioned
      adversarial audit,
      `phase-2b-corpus-cutover/inventory/adversarial-audit/`) downgraded
      15 posts (6 unreachable source, 9 body-level errors including a
      fabricated NASA-official quote) and corrected 15 more; round 2
      (`noticiencias/docs/audits/phase2b-second-independent-audit.md`)
      corrected 14 of those 15 plus 5 more downgraded posts' bodies and
      promoted 3 back to v2 (`noticiencias` PRs #137/#138).
- [x] Reach zero strict editorial errors.
      `node scripts/check-editorial-fields.js --json` reports zero errors
      across the full corpus (23 v2 posts, 2026-09-14, after the 4
      corrections above) — no `STRICT_EDITORIAL=true` prefix needed since
      enforcement is unconditional (see next line).
- [x] Make frontend v2 semantics/checker unconditional and remove CI/deploy
      bypass. Verified 2026-09-14: `STRICT_EDITORIAL` no longer appears
      anywhere in frontend source/tests (`content.config.ts`,
      `check-editorial-fields.js`, `tests/content-config-schema.test.ts`)
      — this had already been done in an earlier session but was never
      checked off here; corrected the stale bookkeeping.
- [x] Prove producer and consumer reject every partial-v2 fixture. Producer
      (backend) side proven by Phase 2a; consumer (frontend) side proven
      by `tests/content-config-schema.test.ts` (unconditional now, not
      `STRICT_EDITORIAL`-gated) — reconfirmed 2026-09-14.

**Phase 2c — real fact-checking against the original source.** Implemented:
new articles get `fact_check` statuses from a genuine comparison against
the article's own stored source `content` (not self-assessment against the
model's own draft), verified on a dedicated Ollama model (`qwen3-next`,
independent of the NVIDIA drafting model), with a `disputed` verdict
blocking publication via `GeneratedArticleValidationError`
(`error_code="editorial_fact_check_disputed"`) the same way Phase 2a's
completeness gate does. See `phase-2c-real-fact-check/spec.md` and
`phase-2c-real-fact-check/todo.md` (fully checked off). **Does not block,
and is not blocked by**, Phase 2b's remaining items above (the operator's
own `reviewed: true` pass, unconditional `STRICT_EDITORIAL` enforcement,
the producer/consumer partial-v2 proof) — those items are about schema
*completeness* and human sign-off; Phase 2c is an orthogonal *content*
verification added on top, per spec.md's header.

### Phase 3 — durable lifecycle schema

- [x] Add additive Alembic migrations for workflow runs, stage attempts,
      editorial decisions, publication attempts, and publication events.
      (Phase 3a, revision `effe4ec70d6d`. Pure additive schema, no
      repository code, nothing reads/writes these tables yet.)
- [x] Add constraints, indexes, delivery idempotency, and collection active-key
      uniqueness. (Phase 3a — RESTRICT FKs, named CheckConstraints matching
      the existing `ck_article_status` convention, unique
      `(workflow_run_id, stage_name, attempt_number)` triple, SQLite
      partial unique index for one active collection. Also enabled
      `PRAGMA foreign_keys=ON` globally as a prerequisite for RESTRICT to
      mean anything — tested safe against the full suite first. One
      latent effect flagged for 3b: `delete_article()` can now raise
      `IntegrityError` instead of returning `False` when RESTRICT-
      protected history exists; nothing hits this path yet since nothing
      writes to the new tables.)
- [x] Add typed repositories and compare-and-set/append-only transitions.
      (Phase 3b — `LifecycleRepository`, exposed as `db.lifecycle`. CAS
      via `UPDATE ... WHERE state = <expected>` with a rowcount check,
      not a version column — no such precedent existed in this codebase
      before this phase.)
- [x] Deterministically backfill known legacy publication/audit state.
      (Phase 3b — `scripts/backfill_lifecycle_tables.py`, fixture-tested
      per the recon finding that the local dev DB has zero rows with
      legacy publication/audit metadata despite real published content
      existing, so it can't validate the backfill itself. Honest scope
      note: only `publication_attempts`/`editorial_decisions` are
      backfillable from real legacy data — `workflow_runs`,
      `workflow_stage_attempts`, and `publication_events` have no legacy
      data to backfill from and start empty by design.)
- [x] Dual-write legacy projections and new records. (Phase 3c —
      `storage/database.py`'s five publication/audit facade methods
      (`mark_article_publishing`, `mark_article_published`,
      `reject_publication_attempts`, `complete_publication_attempts`,
      `update_article_audit_status`) now write into
      `publication_attempts`/`editorial_decisions` alongside their
      unchanged legacy `article_metadata` writes — best-effort, gated on
      the legacy write's own success, never raised into the caller.)
- [x] Add and run the consistency report plus the full migration proof.
      (Phase 3c — `scripts/lifecycle_reconciliation_report.py`'s
      `--dual-write-since` flag splits `"missing"` into
      `"missing_pre_dualwrite"`/`"missing_post_dualwrite"`, letting a
      "missing" result on/after the dual-write cutover be told apart from
      the known pre-existing backfill gap. Migration
      (`a4d9a4ba00aa_extend_publication_attempts_state_check.py`) proven
      via upgrade/downgrade round-trip against a scratch copy of the real
      dev DB's schema (781 articles) plus the full unit/e2e suite.)

### Phase 4 — collection and source workflows

Split into phase-4a (collection-run half, below) and phase-4b (source-catalog
half — not started), same split as Phase 2 (2a/2b/2c) and Phase 3 (3a/3b/3c).

- [x] Add the durable `CollectionRunWorkflow` and lease/restart recovery.
      (Phase 4a — `news_collector/logic/workflows/collection_run_workflow.py`;
      `recover_expired_leases()` wired into a new FastAPI `lifespan` hook in
      `serving/api.py`'s `create_app()`, the first process-startup hook this
      codebase has needed at all.)
- [x] Return typed 409 for a second active collection; named unknown status is
      404. (Phase 4a — `admin_collect`/`admin_collect_status` are now thin
      wrappers around `CollectionRunWorkflow`; the module-global
      `_admin_runs`/`_admin_run_lock`/`_admin_run_counter`/`_latest_run_id`/
      `_prune_collect_runs` state is deleted outright, no dual-write.)
- [x] Add terminal-only 90-day retention. (Phase 4a —
      `scripts/ops/prune_workflow_runs.py`, on-demand ops script following
      `scripts/ops/purge_short_articles.py`'s shape; `queued`/`running` rows
      are never eligible regardless of age.)
- [x] Add atomic/locked `SourceCatalogWorkflow` with compensation and visible
      reconciliation failure. (Phase 4b — `news_collector/logic/workflows/source_catalog_workflow.py`;
      N+1 was already fixed by plan 110 so the batch-half below needed no new
      code; toggle/reset stay repository-direct as they are DB-only —
      see `phase-4b-source-catalog-workflow/spec.md` implementation record.)
- [x] Batch source circuit-state reads. (Satisfied by plan 110's
      `get_all_circuit_states()`; proven equivalent to the per-source loop
      by `test_bulk_states_match_per_source_lookup_for_the_same_inputs`.)
- [x] Move workflow coordination out of HTTP routes and add concurrency/failure
      tests. (Collection-run half done in Phase 4a; the source-catalog half
      done in Phase 4b — upsert/delete dispatch to the workflow, routes keep
      only request parsing/response mapping.)

### Phase 5 — callback reconciliation and truthful health

- [ ] Version callback delivery IDs and add bounded frontend retry diagnostics.
- [ ] Persist authenticated receipts before processing and deduplicate retries.
- [ ] Apply legal publication-attempt transitions and retain processing errors.
- [ ] Add stale-attempt reconciliation without duplicate PR creation.
- [ ] Drive dashboard health from stored evidence; missing evidence is unknown.
- [ ] Cover lost, duplicate, out-of-order, restart, error, and stale-PR cases.

## Wave C — typed boundaries and smaller modules

### Phase 6 — generated contracts

- [ ] Generate deterministic admin OpenAPI from FastAPI/Pydantic.
- [ ] Pin `openapi-typescript`/`openapi-fetch`; generate and adopt admin client
      endpoint by endpoint.
- [ ] Fail CI on stale OpenAPI/TypeScript artifacts.
- [ ] Split frontend structural Zod schema from Astro runtime/date/semantic
      validation.
- [ ] Generate neutral JSON Schema with stable Zod 4 APIs and explicit date
      handling.
- [ ] Prove Zod/JSON Schema/Pydantic parity on the shared corpus.
- [ ] Retire the regex parser only after one release window of parity.

### Phase 7 — backend decomposition

- [x] Extract publication-attempt recording while reusing existing
      collaborators. (Phase 7a, 2026-09-25 — NEW
      `news_collector/logic/workflows/publication_attempts.py` owns artifact
      naming + JSON persistence + interrupted-attempt preservation + read-back;
      `publication_run_workflow`/`pipeline_e2e` rewired; engine keeps
      compatibility delegates. See
      `plans/060/phase-7a-refinery-recording-audit/`.)
- [x] Extract the target-repository publication workflow collaborator of
      Phase 7. (Phase 7b, 2026-09-25 — NEW
      `news_collector/logic/workflows/target_repo_publication.py` owns branch →
      write → validate → commit/push → PR behind a typed
      `PublicationRequest`/`PublicationDeps`/`PublicationOutcome`; the engine
      delegates and keeps audit + attempt persistence. Identity/image remain
      upstream because the AI editor sits between them (documented deviation).
      See `plans/060/phase-7b-target-repo-publication/`.)
- [x] Extract audit scheduling/recording only where independently testable.
      (Phase 7a, 2026-09-25 — NEW
      `news_collector/logic/workflows/audit_scheduler.py`; the engine
      delegates inject auditor/executor/status-recorder per call so existing
      test seams (`engine.executor`, `engine._last_audit_future`,
      `patch.object(engine, "_record_audit_status")`) keep working. Gates:
      `make lint`, `make type` (3229 passed, ratchet OK), `make test`
      (3216 passed), `make test-boundaries`.)
- [ ] Extract typed EditorAgent stages while keeping `process_article` façade.
- [ ] Split bounded admin route modules after wire characterization.
- [ ] Prove no unapproved Markdown, policy, branch/PR, or API drift.

## Wave D — assets and frontend growth

### Phase 8 — media finalization

- [ ] Extract/test derivative publisher with injected filesystem/Sharp/S3.
- [ ] Reuse attested manifest entries and add bounded concurrency/full
      reconciliation.
- [ ] Define the versioned article-owned media descriptor.
- [ ] Move hero finalization/upload into publication with retry evidence.
- [ ] Make ordinary frontend builds R2-read-only after parity.
- [ ] Retire the sync path only after the compatibility window.

### Phase 9 — frontend growth and UI convergence

- [ ] Fix relative reachability allowlisting; review/delete the 37 findings in
      cohorts; enforce the gate.
- [ ] Characterize and precompute deterministic related-post top-four results.
- [ ] Remove the four verified-unused dependencies/config.
- [ ] Inventory and migrate live template consumers route by route.
- [ ] Supersede two-layer governance only after zero production template
      consumers.
- [ ] Run full build/dist/audit plus 375px/1280px visual and metadata checks.

## Wave E — feedback and final simplification

### Phase 10 — reader correction lifecycle

- [ ] Resolve refinery/content revision identity server-side.
- [ ] Separate and delete contact data according to the privacy contract.
- [ ] Reconcile Worker intake idempotently into backend report/decision records.
- [ ] Add legal admin triage/decision/correction/closure transitions.
- [ ] Link correction publication and deploy evidence before closure.
- [ ] Pass lifecycle, idempotency, abuse, privacy, and publication tests.

### Phase 11 — release proof and repository decision

- [ ] Consolidate duplicated CI steps behind repository-owned commands.
- [ ] Add the side-effect-free complete-v2 cross-repo release smoke.
- [ ] Reconcile all active docs and drift gates.
- [ ] Measure cross-repo overhead for at least one release window.
- [ ] Write the evidence-based keep-split or separate monorepo-migration ADR.
- [ ] Run both repositories' complete required gates from clean checkouts.

## Final closeout

- [ ] Every master-spec done criterion is checked with evidence.
- [ ] Operator runbooks and metrics cover every nonterminal/reconciliation path.
- [ ] Compatibility/rollback windows are closed deliberately; no silent dual
      truth remains.
- [ ] Archive plan 060 and update `plans/README.md` with final SHAs only after all
      phases are complete.
