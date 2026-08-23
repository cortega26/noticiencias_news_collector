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
- [ ] Inventory and human-review the 30 incomplete posts; invent no facts.
      **Partial**: Phase 2b Step 1 produced a machine-drafted inventory
      (27/30 posts drafted, 3 flagged for retry) at
      `phase-2b-corpus-cutover/inventory/`. Human review against real
      sources — the actual gate — has not happened yet; do not check this
      box until Phase 2b Step 2 is done.
- [ ] Reach zero strict editorial errors. (Phase 2b, blocked on the human
      review above.)
- [ ] Make frontend v2 semantics/checker unconditional and remove CI/deploy
      bypass. (Phase 2b item 5, blocked on the line above.)
- [ ] Prove producer and consumer reject every partial-v2 fixture. Producer
      (backend) side proven by Phase 2a; consumer (frontend) side still
      gated behind `STRICT_EDITORIAL` pending Phase 2b.

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
- [ ] Dual-write legacy projections and new records. (Phase 3c, not yet
      planned — depends on 3b's repositories, which now exist. This is
      the risky, behavior-changing half: everything landed so far in
      Phase 3 has been additive/inert.)
- [ ] Add and run the consistency report plus the full migration proof.
      **Partial**: Phase 3b delivered the read-only reconciliation report
      (`scripts/lifecycle_reconciliation_report.py`,
      clean/drift/missing/not_applicable) — the "consistency report" half
      is done. "The full migration proof" implies dual-write exists and
      can be verified end-to-end, which is Phase 3c's job; do not check
      this box until that half lands too.

### Phase 4 — collection and source workflows

- [ ] Add the durable `CollectionRunWorkflow` and lease/restart recovery.
- [ ] Return typed 409 for a second active collection; named unknown status is
      404.
- [ ] Add terminal-only 90-day retention.
- [ ] Add atomic/locked `SourceCatalogWorkflow` with compensation and visible
      reconciliation failure.
- [ ] Batch source circuit-state reads.
- [ ] Move workflow coordination out of HTTP routes and add concurrency/failure
      tests.

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

- [ ] Extract publication-attempt recording and target-repository publication
      workflow while reusing existing collaborators.
- [ ] Extract audit scheduling/recording only where independently testable.
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
