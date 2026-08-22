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

- [ ] Add matching ADRs for durable state, generated contracts, and the
      harden-before-consolidating repository decision.
- [ ] Add the versioned shared publication valid/invalid fixture corpus.
- [ ] Add deterministic OpenAPI/publication schema snapshot commands.
- [ ] Preserve the strict editorial failure inventory as migration input.
- [ ] Verify snapshot generation twice with byte-identical output.

### Phase 1 — small security, CI, dashboard, and docs gaps

- [ ] Pin and checksum-verify the Gitleaks download in backend CI.
- [ ] Correct backend active publication-date docs and drift assertions.
- [ ] Wire the frontend search budget into a fresh-build CI path and add pass/fail
      fixtures.
- [ ] Make live and snapshot contract-sync commands strict.
- [ ] Replace dashboard hard-coded passes with measured values or `unknown`.
- [ ] Correct frontend Node/schema/image/build/CI/legacy-fallback active docs.
- [ ] Run each repository's applicable doc and CI gates.

## Wave B — correctness and durable orchestration

### Phase 2 — truthful schema v2

- [ ] Characterize complete/empty/partial/invalid/cached/provider-failure v2
      assembly.
- [ ] Fail incomplete new v2 output before writer/Git side effects with a stable
      retryable error code.
- [ ] Replace the backend v1 smoke fixture with deterministic production-path v2.
- [ ] Inventory and human-review the 30 incomplete posts; invent no facts.
- [ ] Reach zero strict editorial errors.
- [ ] Make frontend v2 semantics/checker unconditional and remove CI/deploy
      bypass.
- [ ] Prove producer and consumer reject every partial-v2 fixture.

### Phase 3 — durable lifecycle schema

- [ ] Add additive Alembic migrations for workflow runs, stage attempts,
      editorial decisions, publication attempts, and publication events.
- [ ] Add constraints, indexes, delivery idempotency, and collection active-key
      uniqueness.
- [ ] Add typed repositories and compare-and-set/append-only transitions.
- [ ] Deterministically backfill known legacy publication/audit state.
- [ ] Dual-write legacy projections and new records.
- [ ] Add and run the consistency report plus the full migration proof.

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
