# Pipeline Contracts

Status: Active  
Authority: Subordinate to `docs/SOURCE_OF_TRUTH.md`, `docs/AGENTS.md`, and `docs/ARCHITECTURE.md`

## Purpose

This document records the contract-bearing flows that matter operationally today: what artifact crosses a boundary, who owns it, and what failure behavior exists in code now.

It intentionally distinguishes current behavior from desired future hardening.

## Contract Inventory

| Flow | Producer | Consumer | Contract / Artifact | Current behavior |
| --- | --- | --- | --- | --- |
| Collection export | `news_collector/system/reporting.py` and collector entrypoints | `apps/refinery/main.py` | `ExportContractV2` from `news_collector/contracts/export.py` | `schema_version: 2` is the preferred path; legacy `schema_version: 1` is still tolerated with warnings |
| Scoring boundary | workflow/system code | scoring modules | `ArticleScoringData`, `ScoringInputModel` | adapter-owned mapping in `news_collector/contracts/adapters.py` |
| Validation boundary | workflow/system code | validation modules | `ArticleValidationPayload` | adapter-owned mapping in `news_collector/contracts/adapters.py` |
| Editorial preparation checkpoint | `EditorAgent.prepare_article()` and Refinery workflow | durable publication recovery | `EditorialDraft`, `PublicationCheckpoint`, `PublicationItemOutcome` | backend-only draft and original source snapshot; media is resolved before creating an `AstroPost` |
| Frontend publication artifact | `news_collector/logic/workflows/refinery_engine.py` | sibling frontend repo | frontmatter/body matching `AstroPost` mirror in `news_collector/contracts/frontend_schema.py` | cross-repo mirror of `../noticiencias/src/content.config.ts` |
| Read API | `news_collector/serving/api.py` | HTTP clients | `ArticleListParams`, `ArticlesEnvelope` | deterministic cursor pagination and validated query parameters |
| Admin API (Phase 1) | `news_collector/serving/api.py` | Astro admin GUI | `news_collector/contracts/admin.py` shapes | read-oriented triage/detail/health/analytics/config under `ADMIN_API_KEY`; mutations dispatch to existing storage/workflow modules |
| Admin GUI (Phase 2) | `apps/admin/` (Astro 7 + Tailwind 4) | `news_collector/serving/api.py` `/v1/admin/*` | typed TS mirrors of `contracts/admin.py`; the four workflow run models are generated from `apps/admin/openapi.json` (plan 080 Phase 2) | token in localStorage with `PUBLIC_ADMIN_API_KEY` build-time fallback; Bearer header; CORS allowlist via `ADMIN_CORS_ORIGINS` |

## Export To Refinery

### Preferred Contract

- top-level export shape: `ExportContractV2`
- article shape: `ExportArticleModel`

### Current Compatibility

- `apps/refinery/main.py` still supports legacy export payloads and missing/invalid `schema_version` through compatibility handling
- this is real compatibility surface, not a theoretical note

### Current Failure Semantics

- invalid or missing export artifacts do not necessarily stop all Refinery usage
- Refinery code contains fallback paths, including database-backed candidate loading in the UI path
- those fallback paths reduce operator dead-ends, but they also mean the export artifact is not the only current ingress path

## Frontend Publication Contract

### Authoritative Shape

The backend mirror is:

- `news_collector/contracts/frontend_schema.py`

The render authority is:

- `../noticiencias/src/content.config.ts`

### Generated JSON Schema Artifact (plan 175)

- Source of truth: `../noticiencias/src/schemas/post.schema.json`, generated
  from `postStructuralSchema` in `../noticiencias/src/schemas/post.ts` with Zod
  4's `z.toJSONSchema` (JSON Schema 2020-12). Regenerate with
  `npm run schema:update`; never edit the artifact by hand.
- Structural scope only: property names, required fields, enum values, basic
  types, nested object/array shapes, `additionalProperties` (top-level extras
  allowed; `social` strict), formats, patterns, and bounds. The parity test
  enumerates the only permitted bound differences (Zod safe-integer/item
  bounds and Pydantic `HttpUrl` length bounds). The artifact represents `date`
  as `oneOf` `date`/`date-time` strings to match this corpus and Pydantic's
  `Union[date, datetime]`.
- Semantic rules that `superRefine` cannot encode are explicit gaps, not
  artifact failures: the five `v2-missing-*` fixtures under
  `../noticiencias/tests/fixtures/publication-contract-corpus/invalid/`
  (summary-points, glossary, fact-check, confidence, sources) pass the artifact
  and are rejected by Pydantic and the full frontend schema. The
  `v2-missing-why-it-matters` fixture there is a frozen stale label that is
  valid on both sides (P0-06/DEC-003). `format: "uri"` accepts the `ftp://`
  source-URL case that Pydantic's `HttpUrl` rejects, and calendar invalid dates
  are rejected by both.
- Coverage is transitive: `tests/test_post_schema_parity.py` compares the
  artifact with `AstroPost.model_json_schema()` structurally (no `jsonschema`
  dependency), while `../noticiencias/tests/post-json-schema.test.ts` validates
  the shared corpus against the artifact with Ajv and against Zod. CI's `type`
  and `test` jobs sparse-checkout and copy the artifact plus
  `../noticiencias/tests/fixtures/publication-contract-corpus/` next to the
  schema module.

### Current Publication Path

- output directory: `src/content/posts/` in the target frontend repo
- file naming: `<canonical-slug>.md`
- sidecar manifest: `refinery_manifest.json`
- category resolution reads top-level export `category` first, then falls back to `metadata.category`
- refinery-generated posts must publish exactly one primary category from the current editorial taxonomy
- `Editorial` is reserved for first-party Noticiencias-authored pieces; translated third-party articles must resolve to a non-`Editorial` category
- optional `social` object (`{publish: bool = false, id?: 64-char lowercase hex}`): social-distribution opt-in stamped deterministically by `contracts/social_publication.py` at Markdown write time (absent by default; explicit `null` rejected on both sides; the LLM never decides it)
- `sources[]` items accept optional `role` (`primary` | `secondary`) and `doi` (`10.xxxx/...`): producer stamps `role: primary` + DOI only for a verified primary paper/preprint; absent role renders as secondary (frontend Wave 2 P0-01; no backfill required)
- optional `evidence_subject_type` (humans | animals | in_vitro | computational | observational | experimental | mixed | unknown) + `evidence_detail` (≤280 chars): producer records the verified experimental model, never inferred (frontend Wave 2 P0-02)
- `why_it_matters` allows 0–3 items with no minimum: producer omits implications rather than fabricating them (frontend Wave 2 P0-06 / DEC-003; `max_length=3` enforced on both sides)
- Wave 3 accountability fields (all optional; producer stamps only verified data, reviewer identity never invented): `institution`, `publication_status` (peer_reviewed | preprint | conference | other), `reviewer_name`/`reviewer_role`/`reviewer_profile_url`/`review_date`, `known_points`/`open_questions` (≤3 each), `corrected_at` + `correction_summary` (travel together)

### Current Identity Reuse Order

`RefineryEngine` currently resolves publication identity in this order:

1. database `canonical_slug`
2. existing frontend file or sidecar manifest
3. `published_date`
4. `collected_date`
5. quarantine (`UndatedArticleError`) when neither date exists

Plan 058 (2026-08-13) removed the runtime-clock fallback: an article with
neither `published_date` nor `collected_date` is no longer silently dated
with the current date — it fails deterministically and is quarantined for
human review. The two remaining fallback steps (`published_date` →
`collected_date`) are compatibility debt, not the desired end state for
immutable identity, but they no longer include a non-deterministic path.

### Publication State Semantics

- PR creation updates backend state to `PR_CREATED`
- optional auditor execution happens after PR creation
- final frontend site publication occurs after merge and frontend deploy, outside this repo

### Self-Corrective Validation (Bounded)

The frontend publication gate classifies its failures
(`PublicationFailureClass`). Two deterministic self-healing layers operate on
top of that contract:

1. **Preventive** — `taxonomy/normalizer.py` repairs characters the
   cross-repo tag contract rejects (`allowed_chars_regex`, shared with the
   frontend `check:tags`) before the post is written; repairs are recorded in
   the normalize audit.
2. **Corrective** — `TargetRepoPublicationWorkflow` consults the pure repair
   registry in `validation/publication_repairs.py` when the fast frontmatter
   guard or the full frontend validation fails. A strategy may only return a
   repair when the contract invariant it targets passes afterwards; the
   workflow re-runs that validation phase **once** (never a loop). A repair
   is surfaced as the `validation_self_repair` stage with the failure class
   and changed fields. Failure classes without a strategy fail exactly as
   before.

A clean pre-PR failure (file write or validation, i.e. nothing committed or
pushed) releases the article's `publishing` state back to the publishable
`completed` status and closes the attempt row as `REJECTED`
(`db.release_article_publishing`, `publishing_state_released` stage). Failures
after commit/push keep `publishing` so the crash-recovery path can resume the
pushed branch. PR creation itself is never retried by the repair loop.

## API Contract

The serving layer exposes public reads and authenticated admin workflow dispatch:

- validated request parameters via `ArticleListParams`
- deterministic cursor encoding using score, collected timestamp, and article ID
- envelope response shape via `ArticlesEnvelope`
- admin surface (`/v1/admin/*`, plan 059 Phase 1): triage queue, article
  detail, source health, analytics, sanitized config read, plus
  audit-status/reject mutations that dispatch to existing idempotent
  storage transitions — authenticated with a distinct `ADMIN_API_KEY`
  (constant-time Bearer, fail-closed outside `development`)
- admin GUI (`apps/admin/`, Phase 2): Astro 7 + Tailwind 4 client of the
  admin surface; cross-origin access allowed only for origins listed in
  `ADMIN_CORS_ORIGINS` (default localhost:4321/4322)
- admin operational surface (Phase 3): collect trigger (async run + status
  poll), article reprocess, source manager (list/toggle/reset circuit),
  config save (full-schema validation, secrets dropped), prompt lab
  (config/prompts.yaml round-trip), published-content snapshot, image
  queue — all dispatching to existing storage/workflow modules. Collect
  trigger/status is now durable (Plan 060 Phase 4a): the `workflow_runs`
  table (not process memory) is the source of truth via
  `CollectionRunWorkflow`
  (`news_collector/logic/workflows/collection_run_workflow.py`) —
  `POST /v1/admin/collect` returns 202 (started) or 409 (a collection is
  already queued/running, existing run id in the body);
  `GET /v1/admin/collect/status?run_id=` returns 404 for an unrecognized
  id rather than substituting the latest run. `AdminRunStatus` now spans
  `queued`/`running`/`succeeded`/`failed`/`cancelled`/`interrupted`. Startup recovery interrupts queued runs and running runs whose lease has expired.
  Starting a new run also recovers expired running leases, without recovering
  queued rows that may belong to an in-flight dispatch. A missing heartbeat
  is stale only when `started_at` is older than the lease cutoff.
- publication trigger/status (`/v1/admin/publish`, `/v1/admin/publish/batch`,
  `GET /v1/admin/publish/status?run_id=`) is durable in `workflow_runs`
  (Plan 060 Phase 4c) and single-flight; an unrecognized run id returns 404.
  Plan 190 supersedes the plan-168 pre-dispatch image gate: missing images
  no longer return `409 image_required`. A valid request begins editing, then
  returns to durable `waiting_for_image` if media is unresolved. A repeated
  pending request reuses its run ID; completed matching revisions reuse their
  stored outcome. `AdminPublicationRunStatus` extends `AdminRunStatus` with
  `waiting_for_image` for publication responses only. Collection keeps its
  existing six-state vocabulary. A queued/running publication still produces
  the normal 409 single-flight conflict.
  Waiting reports `active=false`, no completion timestamp, no live progress,
  no heartbeat and no `typical_seconds`; the GUI keeps polling without ETA or
  stalled-worker warnings. The response exposes `editorial_completed_count`,
  `waiting_for_image_count`, `image_reason` and `image_brief_slug` in addition
  to its persisted summary. Batch items distinguish `succeeded`, `failed` and
  `waiting_for_image`. `processed_count` counts PR successes; zero PRs with
  pending images is not an execution error.
  While a run is queued/running `AdminPublishStatus` also carries **advisory
  live progress**: the article's recorded Refinery stage names
  (`progress.stages`, fed by the `RefineryEngine.stage_listener` hook),
  `progress.item_index`/`item_count` for batch runs, the lease
  `heartbeat_at`, and `typical_seconds` (median wall time of the most recent
  successful single-article runs, batch runs excluded in SQL before the
  sample cap — the admin GUI's ETA baseline). Recording progress is
  deliberately non-blocking: a listener or progress-write failure is logged
  and can never alter the publication outcome (LAW-B7).
- webhook inbox (ADR-0011): `GET /v1/admin/webhook/receipts?after_id=&limit=`
  returns this instance's durable callback receipts — raw payload, **every**
  status (the sender's processing outcome says nothing about a consumer with
  its own database), ordered by id — so the local system of record can replay
  them through the same `handle_webhook_event` path (idempotent by delivery
  key). `scripts/ops/pull_webhook_receipts.py` / `make webhooks-pull` stages
  each hosted page in `webhook_pull_receipts` before advancing the durable
  endpoint cursor in `webhook_pull_cursors`. The cursor proves receipt, not
  application; staged rows keep their payload and retry lease until the local
  handler succeeds. Application stays in hosted ID order: the drain stops at
  the first retryable failure and steps over receipts that exhausted their
  delivery attempts (derived: `status='failed'` with
  `attempts >= MAX_DELIVERY_ATTEMPTS`, 5 — payload and counter are retained,
  no extra status value). For an applying run, exit 0 reports a completed
  pass (malformed and exhausted receipts are a report), 1 reports an
  unexpected failure resolving the endpoint/token or fetching, and 2 reports
  remaining work (pending or leased rows, the safety cap, business
  attention); dry-run exit 0 means parse-only and makes no acknowledgments.
  The endpoint remains read-only and admin-authenticated.
- admin parity surface (Phase 4): unpublish + bulk reset of published
  content (git-backed, plan-017 semantics), image brief edit + asset
  upload (multipart), source delete (sources.yaml + DB)
- published-content capability (plan 151): those three routes read the
  frontend checkout through GitPython, so they require a `git` binary plus a
  frontend checkout (or a clone the serving process can make). Where that
  capability is absent — the hosted serving image ships neither — they answer
  `503` with `error_code=published_content_unavailable` and a message naming
  the missing requirement instead of an import-time `500`. No other admin
  route depends on git, and the local stack is unchanged.
- source editor (Phase 4 addendum): add/update sources via
  POST /v1/admin/sources (merge preserves blacklist/etag keys; create
  seeds the old GUI defaults plus the catalog-required
  `tier`/`fetchability_score`/`crawl_interval_seconds`); CORS now allows
  PUT/DELETE for the unpublish/upload/delete flows. Catalog writes
  (upsert/delete) are now serialized and atomic via
  `SourceCatalogWorkflow` (Plan 060 Phase 4b) under a documented
  single-writer assumption (`docs/database_deployment.md`); their new
  failure contracts are `409` (catalog locked by a concurrent mutation)
  and `500` with a `reconciliation_required` marker row in
  `workflow_runs` when a DB-sync failure could not be compensated.
  Toggle/reset are DB-only (active/circuit state never lives in
  `sources.yaml`).

The serving layer is not the owner of editorial mutation workflows.

## Frontend publication callback identity

`publication_ids` contains stable `refinery_id` article identities; it does not
identify a publication attempt. State-changing frontend callbacks must also
carry `publication_attempt_refs`, one per affected article, with the exact
`refinery_id`, positive GitHub pull request number, and lowercase SHA-256 of
the Markdown bytes tested or deployed. The backend matches all three against
the stored `pr_created` event before changing an attempt. Missing, ambiguous,
or stale references remain visible as business attention and do not mutate an
unrelated attempt. A validation failure cannot be reversed by a later callback
for that same attempt; a later retry must identify its own PR/content attempt.

## Current Gaps To Treat As Gaps

- The backend's own parity test (`tests/test_contracts_sync.py`) covers only top-level field names; the full type/constraint/optionality comparison is enforced by the frontend's checker, which backend CI runs in strict mode (`.github/workflows/ci.yml` → `contract-parity` job) and the frontend runs on every push (Content Guard).
- Frontend validation-failure notifications (`POST /api/v1/webhook/frontend`, `serving/api.py`) depend on `BACKEND_WEBHOOK_URL`/`BACKEND_WEBHOOK_TOKEN` being configured in the frontend repository — they must be set for the failure loop to close.
- Webhook deliveries are persisted as durable receipts before processing (plan 060 Phase 5a, `webhook_receipts`): the endpoint answers 202 only after the receipt exists, an optional `delivery_id` (or a stable derived key when absent) makes replays idempotent — a duplicate of a processed delivery returns its stored result without reapplying transitions — and a processing exception leaves a `failed` receipt with its error and attempt count. The frontend sender does not yet emit `delivery_id` or bounded retries; the derived key covers that gap until it does. Inbound payloads are bounded before persistence (plan 142): the route rejects raw bodies over 2 MiB with 413, and the envelope caps `diagnostics` (50) and each diagnostic's `errors` (5000 items / 1 MiB serialized) plus the free-form audit fields (`commit_sha` 128, `branch`/`frontend_ref` 255, `run_url` 2048 characters) — all far above what CI sends, so the append-only receipt log cannot be grown without bound by a caller holding the shared key.
- Publication-attempt transitions are audited (plan 060 Phase 5b, `publication_events`) and restricted to the explicit legal map `PUBLISHING → {PR_CREATED, REJECTED, COMPLETED}`, `PR_CREATED → {REJECTED, COMPLETED}`, terminal states permit nothing; the state change, event, and current-article projection update are written in one transaction. Callbacks match by `publication_attempt_refs` (article ID + PR number + exact-content SHA-256); a validation *pass* appends `check_passed` without changing state.
- Crash recovery reuses the stored workflow attempt ID and fingerprints the exact Markdown file from the target checkout before recreating or recovering a PR. If the source artifact cannot be read, recovery refuses to create an uncorrelated PR; legacy rows without an ID receive a new recovery ID.
- Stale `PR_CREATED` attempts are reconciled on demand by `scripts/ops/reconcile_publication_attempts.py` (plan 060 Phase 5b): it replays unprocessed receipts (`received`/`failed`) whose `publication_ids` name a candidate, repairs an attempt whose legacy article is already `completed` **with a real deploy URL** or already `rejected`, and reports an otherwise-stale open PR as actionable. It never creates a pull request and never marks an attempt `COMPLETED` without deploy evidence.
- The dashboard's backend-owned health evidence is read at `GET /v1/admin/dashboard/health` (plan 060 Phase 5c, admin-token protected): publication attempts, webhook receipts, and Content Guard outcomes, each with `evidence: "none"`/`status: "unknown"` when no record exists to judge from — a zero-row query is never reported as `pass`. The frontend dashboard combines it with its own schema/hero-image/lint records (phase 5d) and keeps any area without evidence `unknown`.
- Publication identity reuse is strong but still has fallback branches that can use non-source dates.
- `RefineryEngine` remains broader than ideal and mixes several responsibilities inside one workflow module.

## Editorial checkpoints and image readiness (plan 190)

`contracts/editorial_draft.py` defines the sealed, media-free editorial
projection. Its editorial fields retain the existing validators; only the
image dependency is deferred. `EditorAgent.process_article()` remains the
compatible prepare-and-assemble wrapper. An internal preview is not a valid
frontend post. Final assembly must satisfy the unchanged `AstroPost` mirror.

`contracts/publication_checkpoint.py` defines `PublicationCheckpoint`, canonical
`CheckpointIdentity` and `PublicationItemOutcome`; structural conversion from
pipeline results lives in `contracts/publication_checkpoint_adapters.py`.
`storage/publication_checkpoint_repository.py` owns their atomic persistence in
`workflow_runs.run_metadata`. The source snapshot, prepared draft, fingerprint,
brief reference and per-item outcomes survive restarts and export replacement.
The fingerprint includes editorial inputs, prompts, models and policy while
excluding image fields. Media-only resolution reuses validated work without
repeating editorial LLM calls; changed editorial inputs require preparation
again. A rejected sibling can retain a typed outcome without a draft.

Image briefs retain their existing statuses. An accessible URL or local path
alone does not establish redistribution rights. Staged-asset readiness requires
a valid decoded asset, matching asset evidence and approved provenance
(`ai_generated`, `licensed` or `original`); `image_origin=unknown` cannot release
a wait. The existing remote-image host allowlist remains an explicit reuse
policy for source downloads. Final assembly supplies usable alt text through
the existing description/headline fallback. Missing, placeholder,
download-failed and unproven-rights assets defer only publication. Optional
`ImageGenerationMetadata` records prompt, tool, SHA-256 and dimensions; upload
validates the supplied hash and size against actual bytes and the brief also
records `asset_sha256`, `asset_width` and `asset_height`. Pillow 12.3.0 is pinned
in the base runtime lock as well as the existing Refinery lock; decoding actual
bytes no longer depends on installing the Streamlit extra. Codex can
generate and review assets through its built-in `imagegen` during an active
session; the server does not call an unattended generation API.

## Workflow lifecycle and client boundaries

`CollectionRunWorkflow` and `PublicationRunWorkflow` own `workflow_runs` status
rows. The database enforces one queued/running run per run type. The default
lease is 3,600 seconds with a 60-second heartbeat cadence. Publication's
`waiting_for_image` rows do not hold the active slot, heartbeat or
`finished_at`. Atomic claims of those rows arbitrate ready-image and busy-slot
races without creating a new request.

The serving lifecycle reconciles at startup, approved asset registration,
worker completion and every 15 seconds. Checkpoint-bearing orphaned publication
runs are recovered into resumable waiting; runs without durable replay evidence
remain `interrupted`. Collection recovery keeps its existing interruption
semantics. Replay reuses terminal siblings and persisted PR evidence; database
claims and publication identity checks do not imply exactly-once external
GitHub effects or general multiple-worker support.

Publication start accepts exactly one of `article_id` or `article_url`; it has
no publication dry-run switch. Editorial completion, waiting, workflow success,
PR creation and frontend deployment acknowledgment are distinct states.

The four collect/publish started/status response types are generated from
`apps/admin/openapi.json`; other admin interfaces remain handwritten where
shown in `apps/admin/src/lib/types.ts`. Use `make admin-contracts-generate` and
`make admin-contracts-check` for deliberate schema changes.
`apps/admin/src/lib/api.ts` uses the localStorage/build-time token fallback and
development bypass. `PUBLIC_ADMIN_API_KEY` is browser-visible and is not a
server-only secret. Waiting requests remain independently watched in Curaduría;
links from the article and image desks carry the run ID for continued polling.

## Image-wait migration and rollback

Apply Alembic revision `f190a1b2c3d4` (for example, `make migrate`) before starting
the compatible backend and regenerated admin. It extends the workflow status
constraint and restricts `waiting_for_image` to publication rows; it does not
change collection states or the frontend post schema. Verify the migration and
resume flow on a database copy before a live rollout.

For rollback, stop the serving process first so its reconciler stops and joins
before replacing code; preserve a database backup and every checkpoint. Leaving
the upgraded schema in place is preferable to discarding pending work. The
migration refuses downgrade while any row is `waiting_for_image`. Before an
older backend or a schema downgrade is used, resolve those requests or perform
an explicit maintenance transition to `interrupted` that preserves
`run_metadata` and its checkpoints. There is no destructive automatic rewrite
in the downgrade. Interrupted checkpoints remain retained for controlled
recovery after compatible code is restored; do not delete them to satisfy the
constraint.
