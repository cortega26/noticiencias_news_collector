# Plan 049: Spike a versioned publication feed and deterministic materializer

> **Executor instructions**: Preserve the direct Git/PR publication path as the production control. Build only a local fixture-level producer/materializer and a comparative ADR; do not introduce a second production source of truth during the spike. Update plan 049 in `plans/README.md` when complete.
>
> **Drift check (run first)**:
> `git diff --stat e43bd30..HEAD -- news_collector/logic/workflows/target_repo_writer.py news_collector/logic/workflows/publication_identity.py news_collector/logic/workflows/pr_orchestrator.py news_collector/logic/workflows/refinery_engine.py news_collector/contracts tests/e2e_cross_repo docs`
> `git -C ../noticiencias diff --stat 0cdca74..HEAD -- src/content.config.ts src/utils/blog.ts src/content/posts scripts tests docs`

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: MEDIUM
- **Depends on**: plans/020-enforce-cross-repo-schema-parity.md, plans/021-rebuild-publication-callback-contract.md, plans/022-block-executable-published-content.md, plans/028-enforce-v2-editorial-contract.md, plans/041-add-whole-workspace-verification.md
- **Category**: direction
- **Planned at**: backend `e43bd30`, frontend `0cdca74`, 2026-07-21

## Why this matters

Today the backend edits the frontend repository directly and opens one content branch/PR. That is simple and auditable, but it couples producer execution to frontend filesystem layout and makes replay, multi-consumer delivery, atomic batches, tombstones, and revision rollback implicit in Git operations. A versioned immutable feed may improve recovery and consumer decoupling—but only if a small deterministic prototype proves benefits greater than its operational cost.

## Current state

- `TargetRepoWriter.write_article` writes Markdown directly under frontend `src/content/posts`, updates `refinery_manifest.json` from article ID to filename, and prunes a related allowlist.
- `PublicationIdentityResolver` derives/recovers the immutable date-prefixed slug from database or manifest and uses filesystem collision checks for new content.
- `RefineryEngine.process_single_article` creates a branch, marks `publishing`, writes the post/manifest, runs frontend validation, commits/pushes, and asks `PROrchestrator` to create a PR.
- `PROrchestrator.create_pr` currently marks the database article published when a PR URL exists; plan 021 replaces that premature state transition with correlated validation/deploy completion.
- Frontend `src/content.config.ts` uses Astro's glob loader over `src/content/posts/**/*.md`; `src/utils/blog.ts` renders/normalizes that collection. There is no feed consumer or second content store.
- Existing cross-repo publication tests stage a Markdown fixture plus sidecar manifest into a temporary frontend and run all content/build gates, providing a useful compatibility oracle for a prototype materializer.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Feed prototype | `.venv/bin/python -m pytest tests/spikes/test_publication_feed.py -q` | envelope, replay, integrity, tombstone, rollback, and path-safety fixtures pass |
| Cross-repo materialization | `.venv/bin/python -m pytest tests/e2e_cross_repo/test_publication_feed_materializer.py -q` | generated Markdown/manifest pass the existing frontend publication validator |
| Determinism trial | `.venv/bin/python scripts/spikes/publication_feed_trial.py --fixtures tests/fixtures/publication_feed --revisions 1000 --output reports/spikes/publication-feed.json` | two clean replays have identical tree/content hashes and bounded runtime/disk metrics |
| Documentation gates | `make context-validate && git diff --check -- docs && npm --prefix ../noticiencias run check:doc-drift` | context index, Markdown whitespace, and frontend contract references pass |

## Scope

**In scope**: feed use cases/non-goals, versioned envelope and revision semantics, local producer/materializer prototype, hashes/path guards/tombstones/corrections, deterministic replay/rollback/batch tests, security/ownership analysis, comparison with direct PR publication, and build/no-build ADR.

**Out of scope**: production feed storage/service, changing frontend content loader, dual-writing production, Kafka/queue infrastructure, public API commitments, replacing Git review, migrating existing articles, or selecting a cloud vendor.

## Git workflow

- Branch: `advisor/049-publication-feed-spike` in the backend; touch frontend only for temporary fixtures/tests if essential.
- Commit example: `research: evaluate versioned publication feed`.
- Keep all prototype modules under an explicitly non-production `scripts/spikes`/`tests/spikes` boundary.

## Steps

### Step 1: Define decision-driving use cases

Quantify current pain and desired capabilities: failed PR recovery, multi-article atomicity, correction/tombstone propagation, reproducible rollback, consumer decoupling, audit history, publish latency, and future consumers. Record which are already solved sufficiently by Git plus plans 020/021/041.

**Verify**: `docs/spikes/versioned-publication-feed.md` has baselines or clearly marked unavailable evidence, named consumers/operators, prioritized use cases, and explicit reasons not to build a feed.

### Step 2: Specify a minimal immutable contract

Design a versioned feed revision/envelope with feed/schema version, monotonic revision/parent, producer commit/config/model versions, generated time, entry operation (`upsert`/`tombstone`), stable `refinery_id`, canonical slug/path, content/frontmatter/asset hashes, prior/correction lineage, and batch hash. Define canonical serialization, ordering, duplicate/idempotency behavior, compatibility, retention, and snapshot/compaction semantics.

**Verify**: JSON Schema/Pydantic fixtures reject unknown versions, invalid transitions, duplicate identities/paths, hash mismatch, path traversal, orphan parent, and tombstone without prior identity.

### Step 3: Prototype a pure producer and materializer

Build fixture-only functions that package approved Markdown into revisions and materialize any selected revision into a clean temporary frontend tree plus existing `refinery_manifest.json`. Validate content with the contracts from plans 020/022/028 before writing; use atomic staging/rename; never execute MDX or fetch assets. The materializer output, not the feed, remains input to the existing frontend validator.

**Verify**: same feed revision always yields the same sorted file tree and byte hashes; invalid content/hash/path leaves the previous tree untouched.

### Step 4: Exercise replay, correction, deletion, and rollback

Create synthetic histories for initial publish, idempotent replay, changed title with stable identity, correction revision, slug/path conflict, tombstone, batch partial failure, consumer interruption, unknown future version, and rollback to a prior snapshot. Compare append-only event replay with periodic snapshots/compaction.

**Verify**: 1,000-revision clean and interrupted replays converge; rollback selects an immutable prior revision without rewriting history; materialized current state passes frontend full publication validation.

### Step 5: Threat-model and operate the design

Cover forged/tampered feed, compromised producer, rollback/replay attack, path traversal, executable content, oversized batch/assets, revision gaps, unavailable/corrupt store, leaked drafts, signing/key rotation, retention, backup, observability, and single-writer/concurrency. Decide whether Git commit/blob hashes are sufficient or a separate signature/trust root is justified.

**Verify**: every trust boundary has preventive/detective controls, owner, recovery, and secret/key handling; prototype verifies hashes and fails closed without production credentials.

### Step 6: Compare against the direct PR path and decide

Run the same synthetic publication/correction/recovery scenarios through the current local PR simulator and feed prototype. Compare code/operational complexity, failure steps, deterministic recovery, latency, disk/storage, review UX, security, migration cost, and support burden. Approve a feed only if prioritized capabilities cannot be met more simply by strengthening Git artifacts/manifests.

**Verify**: ADR states `build`, `defer`, or `do not build`, evidence/thresholds, architecture owner, staged migration/rollback if approved, and a deletion date for prototype code if rejected.

## Test plan

- Contract/schema compatibility and canonical serialization tests.
- Hash, traversal, size, version, parent, duplicate, tombstone, and corruption negatives.
- Deterministic 1,000-revision replay/interruption/rollback trial.
- Cross-repo materialization through the existing frontend content/build validation oracle.
- Side-by-side local failure/recovery comparison with the direct Git/PR flow.

## Done criteria

- [ ] Decision-driving use cases and current Git-path baselines are explicit.
- [ ] Minimal feed contract and local deterministic materializer are proven with synthetic fixtures.
- [ ] Security, recovery, compatibility, ownership, and operating costs are evaluated.
- [ ] Cross-repo output is identical in contract to existing validated Markdown/manifest input.
- [ ] A decisive build/defer/no-build ADR exists; production remains single-source throughout the spike.

## STOP conditions

- Stop at `do not build` if Git plus existing contract/callback improvements satisfy the prioritized recovery/audit needs.
- Stop if the design requires dual production sources of truth, unowned feed infrastructure, or weaker human review.
- Stop before adding signing/storage/services until threat model, key owner, retention, and recovery are approved.

## Maintenance notes

If approved, split producer, storage, materializer, shadow dual-run, cutover, and decommissioning into separate plans. Preserve Markdown/frontmatter as the frontend boundary until a later independently justified migration.
