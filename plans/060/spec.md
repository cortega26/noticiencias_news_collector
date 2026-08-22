# Plan 060: Cross-repository publication reliability and architecture hardening

> **Executor instructions:** This is a coordinated program across the backend
> and frontend repositories. Execute it as small, reviewable pull requests in
> the wave order below. Do not turn it into a big-bang rewrite, a monorepo
> migration, or a new infrastructure program. Each phase must create or update
> its own implementation `spec.md` and `todo.md`, add characterization tests
> before behavior changes, and update this plan's execution record and
> `plans/README.md` status.
>
> **Drift check (run before each phase):** compare the paths named by that phase
> against backend `d63cbea` and frontend `237cd13`. If a cited contract, table,
> workflow, or public API changed, update this plan before implementing it.

## Status

- **Priority:** P1
- **Effort:** L (multi-wave program; each PR should remain S or M)
- **Risk:** HIGH
- **Category:** correctness / architecture / operations / performance
- **Planned at:** backend `d63cbea`, frontend `237cd13`, 2026-08-22
- **Depends on:** completed plans 021, 028, 041, 043, 047, 049, 057, and
  058; the implemented admin API/Astro admin Phases 1-4 (called “plan 059” in
  `docs/PIPELINE_CONTRACTS.md`)
- **Does not replace:** partial plan 048's enrichment-registry experiment

## Outcome

Make the current product trustworthy and easier to evolve without changing its
core product model:

- keep Astro static, server-first, Git-reviewed Markdown publication;
- keep Python/FastAPI/SQLAlchemy, TypeScript, SQLite, R2, and human approval;
- keep the two repositories during remediation;
- make editorial contracts, workflow state, publication callbacks, admin API
  types, media delivery, and reader corrections explicit and testable;
- reduce the largest implementation concentrations only along proven seams;
- remove unused frontend surface and guard build-time growth;
- re-evaluate repository consolidation only after measuring the remaining
  coordination cost.

The goal is not architectural novelty. It is a deterministic pipeline that can
answer: what happened, which stage failed, what is safe to retry, what was
published, whether the frontend acknowledged it, and which contract each side
validated.

## Repository vocabulary

| Name | Root at plan time | Authority |
|---|---|---|
| **Backend** | `noticiencias_news_collector/` | collection, editorial processing, operational state, publication orchestration, admin API |
| **Frontend** | `noticiencias/` | Astro content schema, published Markdown, static rendering, deployment, reader-report intake Worker |

All paths below are relative to one of those roots and are prefixed with
**Backend** or **Frontend** where ambiguity is possible.

## Evidence baseline

This plan reconciles the findings against current code and completed plans. The
following are measured facts, not target-state assumptions:

| Area | Current evidence | Consequence |
|---|---|---|
| Editorial v2 | Frontend strict audit finds 31 v2 posts; 30 posts fail with 180 missing-field errors. One post is complete. Neither content CI nor deploy sets `STRICT_EDITORIAL=true`. | Do not switch strict mode on before a reviewed corpus repair. Never fabricate sources, fact checks, glossary entries, or confidence. |
| Producer smoke | Backend `frontend_publication_validation.py` still builds a schema-v1 smoke fixture although `EditorAgent` emits v2. | The producer/consumer smoke does not prove the production contract. |
| Contract parser | Frontend `scripts/check-contract-sync.js` is 1,488 lines and regex-parses Python and Zod. Strict comparison currently passes, but package scripts and CI use non-strict mode. | Make the existing gate strict immediately; replace parsing only after a generated neutral contract and shared corpus prove parity. |
| Admin collection | `serving/api.py` stores runs in module globals, launches one daemon thread per request, prunes active history, and substitutes the latest run for an unknown requested ID. | Run state is lost on restart and single-flight is not enforced. |
| Operational history | `Article.processing_status` plus `article_metadata` JSON carries publication and audit state. | Attempts and decisions cannot be queried or reconciled reliably. |
| Source mutation | Admin routes write YAML and SQLite as separate operations; YAML writes are not atomic. Source circuit state is fetched per row. | Partial failure can split the catalog; source listing has an N+1 read path. |
| Publication callback | Frontend logs callback failure but deploy succeeds; backend returns 202 even when processing failed; post-PR attempts are excluded from recovery. | A deployed article can remain indefinitely in `publishing`. |
| Admin types | `apps/admin/src/lib/types.ts` is a handwritten mirror and `api.ts` casts response JSON. | Wire drift is detected late and only where custom tests happen to cover it. |
| Backend concentration | `serving/api.py` is about 1,734 lines, `RefineryEngine` about 1,043, and `EditorAgent` about 2,284. The first Refinery decomposition already exists. | Extract only concrete lifecycle/stage responsibilities; preserve public façades. |
| Images | Frontend build invokes derivative publication; R2 mode checks every variant sequentially. Existing image tests do not characterize publisher orchestration. | Unchanged deploy cost grows with the archive and network mutation is coupled to build. |
| Search | Current gzip artifact is 97,668 bytes under a 150 KiB budget, but the existing budget script is not in CI. | Growth can silently cross the intended limit. |
| Components | Existing reachability checker reports 37 unreachable components but is not in CI. Active governance still mandates `ds` plus `template`. | Prune dead code first; migration to one live system requires a superseding ADR. |
| Related posts | Each article scans and sorts the collection to choose four related posts. | Build work trends toward quadratic / `N² log N`. |
| Dependencies/docs | Four manifest dependencies appear unused. Runtime/schema ADR references and active image/build docs are stale. | Maintenance and supply-chain surface exceed actual behavior. |
| Security workflow | Backend quality CI downloads a Gitleaks archive to `/usr/local/bin` without verifying its checksum. | A privileged job trusts an unverified binary artifact. |
| Reader corrections | The Worker intake is durable, and plan 047 defines an eight-state lifecycle, but triage, revision identity, decisions, and closure are not integrated. | Reports are collected without a closed-loop editorial record. |

### Work already completed—do not repeat it

- Do not reopen PostgreSQL. SQLite is the production database by operator
  decision in plan 046.
- Do not redo deterministic publication-date work from plan 058.
- Do not replace `PublicationIdentityResolver`, `TargetRepoWriter`,
  `ArticleImageHandler`, or `PROrchestrator`; plan 057 already extracted them.
- Do not rebuild the versioned publication feed from plan 049.
- Do not recreate the report intake Worker from plan 023 or the correction
  lifecycle analysis from plan 047; integrate them.
- Do not redo search serialization from plan 039; wire and preserve its budget.
- Do not bulk flatten the UI. ADR-0002 and current governance intentionally
  retain the `ds` and `template` layers until superseded.
- Do not revisit items in
  `docs/audits/2026-08-plans-rejected-findings.md`.

Some current findings extend outcomes that the ledger records as complete. This
is intentional and must be described accurately in implementation PRs:

- plan 028 established the v2 fail-closed direction, but today's corpus and CI
  prove that its strict-enforcement outcome is not currently satisfied;
- plan 021 proved the callback's live authenticated transport, while this plan
  adds durable receipt, retry, and reconciliation semantics;
- plan 043 added doc-drift machinery, while this plan adds specific invariants
  that current checks miss;
- plan 044 introduced pruning/reachability work, while the current unenforced
  checker and 37-file inventory are the measured residual debt.

Do not relitigate those plans' already-shipped foundations. Fix the observed
residual contract and regression surface.

## Target architecture and ownership

```text
Sources/YAML authority
       │ atomic catalog mutation + SQLite operational mirror
       ▼
durable workflow_run ──► typed stage_attempts / editorial_decisions
       │
       ▼
EditorAgent façade ──► typed stages ──► complete v2 artifact
       │
       ▼
publication_attempt ──► Git branch/PR ──► frontend strict CI/deploy
       │                                      │
       └──── publication_event receipt ◄──────┘
                         │ idempotent reconciliation
                         ▼
                 terminal published/failed state
```

Ownership rules:

1. **Frontend Zod remains publication-input authority during migration.** A
   committed generated JSON Schema becomes the neutral exchange artifact only
   after both validators and a shared valid/invalid corpus agree. The generated
   file is not hand-edited.
2. **FastAPI/Pydantic owns the admin HTTP contract.** FastAPI's generated
   OpenAPI document produces the Astro admin TypeScript client and types.
3. **SQLite owns operational lifecycle state.** Git/Markdown owns published
   content; `sources.yaml` owns source catalog configuration; R2 owns binary
   derivatives/reports. Mirrors are explicit and reconcilable.
4. **HTTP routes translate protocols; workflows coordinate mutations;**
   repositories own DB writes; adapters own Git/filesystem/R2/network I/O.
5. **Retries are stage-specific and idempotent.** Deterministic validation and
   policy failures do not get blind retries.

## Data contracts to add

The first migration is additive. Keep current `Article` columns and JSON readers
for one compatibility release and dual-write through repository methods.

### `workflow_runs`

| Field | Required behavior |
|---|---|
| `id` | opaque stable ID returned by the API |
| `kind` | typed value; initially `collection` and `publication_reconciliation` |
| `idempotency_key` | nullable external/request identity; unique with kind when present |
| `status` | `queued`, `running`, `succeeded`, `failed`, `interrupted`, `cancelled` |
| `active_key` | nullable key, set to `collection` only while queued/running; unique SQLite partial index enforces single-flight |
| `requested_payload` / `summary` | versioned JSON contracts, not arbitrary hidden state |
| `error_code` / `error_detail` | stable machine code plus bounded operator detail |
| timestamps | created, started, heartbeat, finished, updated |
| `version` | optimistic transition counter |

Rules: insert before dispatch; compare-and-set transitions; a runner acquires a
lease/heartbeat; startup recovery marks expired active rows `interrupted`;
retention removes terminal rows only (default 90 days, configurable), never
queued/running rows.

### `workflow_stage_attempts`

Append-only rows keyed to `workflow_run_id`, with typed stage, attempt number,
status, input/output identity or hashes, provider/model metadata when relevant,
timestamps, error code, and bounded diagnostic JSON. A unique
`(workflow_run_id, stage, attempt_number)` constraint prevents duplicates.

### `editorial_decisions`

Append-only audit/fact-check/correction decisions keyed to article/refinery ID,
with decision type, outcome, actor class, content revision, rationale,
provenance references, and timestamps. Secrets or reader contact data never
enter this table.

### `publication_attempts`

One row per attempt, keyed to article/refinery identity, with `stage`, `status`,
branch, commit SHA, PR URL/number, deploy identity/URL, content revision, last
error, and timestamps. `status` is `pending`, `running`, `succeeded`, `failed`,
or `cancelled`. Define legal stage advancement explicitly:

`prepared → pushed → pr_created → validation_passed → deployed → acknowledged`

Failures retain the current stage and set attempt status/error; a safe retry
resumes or creates a linked successor according to the stage's idempotency rule.
They do not erase prior evidence.
The existing article `processing_status` is a compatibility projection during
the migration.

### `publication_events`

Persist every authenticated callback before processing. Store event kind,
schema version, delivery/idempotency key, payload hash, source SHA, received and
processed timestamps, processing status/error, and linked publication attempts.
The unique delivery key makes retries safe. Payload retention must remain
bounded and must exclude secrets.

`source_snapshots` and `media_assets` are deliberately deferred until phases 8
and 9 prove concrete consumers. They are not prerequisites for durable jobs.

## API decisions

- `POST /v1/admin/collect` creates a durable row and returns `202`.
- If any collection row is queued/running, a second request returns `409` with
  a typed body containing `active_run_id`; it never starts another collector.
- `GET /v1/admin/collect/status?run_id=<id>` returns that exact row or `404`.
  Omitting `run_id` may return the latest row; the two meanings are never mixed.
- A daemon thread may remain temporarily as an execution mechanism, but it is
  only a runner over durable rows. It is not the state owner.
- Webhook receipt returns `202` after durable receipt. Invalid/auth failures
  remain 4xx. A processing failure remains visible as `failed/pending_retry` on
  the receipt instead of being discarded behind a successful response.
- Replaying a callback operates on the stored event/attempt and is idempotent.
- `sources.yaml` remains catalog authority; SQLite remains the operational
  source/circuit mirror. No silent authority reversal occurs.

## Primary implementation references

Use native, documented generation APIs rather than extending the custom parser:

- FastAPI OpenAPI generation and `app.openapi()`:
  <https://fastapi.tiangolo.com/how-to/extending-openapi/>
- Pydantic `BaseModel.model_json_schema()`:
  <https://docs.pydantic.dev/latest/concepts/json_schema/>
- Astro content collection schema behavior:
  <https://docs.astro.build/en/reference/modules/astro-content/>
- Zod 4 JSON Schema conversion and its unrepresentable-type rules:
  <https://zod.dev/json-schema>
- `openapi-typescript` CLI:
  <https://openapi-ts.dev/cli>
- typed `openapi-fetch` client:
  <https://openapi-ts.dev/openapi-fetch/>

Copy local patterns from these current files:

| Need | Existing pattern |
|---|---|
| DB transaction/rollback | Backend `news_collector/storage/database.py` (`get_session`) |
| Append-oriented history | Backend `news_collector/storage/models.py` (`ScoreLog`) |
| Additive SQLite migration | Backend `alembic/versions/b61c2d3e4f50_add_score_logs_latest_index.py` |
| Migration proof | Backend `tests/test_database_migrations.py` |
| Narrow workflow collaborator | Backend `publication_identity.py`, `target_repo_writer.py`, `pr_orchestrator.py` |
| Administrative interface characterization | Backend `tests/test_serving_admin_api.py` |
| Valid v2 artifact shape | Frontend `src/content/posts/2026-08-12-un-modelo-de-ia-realizo-mas-de-17-500-acciones-en-hugging-face.md` and `tests/content-config-schema.test.ts` |
| Injected script dependencies | Frontend `scripts/r2-image-quota-guard.js` tests/pattern |
| Image descriptor/object key | Frontend `src/utils/image-derivatives.ts` and `scripts/utils/image-derivatives.js` |
| Search budget | Frontend `scripts/check-search-budget.js` |
| Reachability traversal | Frontend `scripts/check-component-reachability.js` |

## Delivery strategy

Use one backend implementation spec/todo pair per phase and matching branch
names where both repositories change, for example
`architecture/060-02-editorial-v2`. Each PR must leave both repositories in a
deployable state. Additive compatibility comes before cutover; cleanup comes
only after telemetry/tests prove the new reader.

### Dependency and parallelism map

| Phase | Hard dependency | Can run in parallel with |
|---|---|---|
| 0 baseline/ADRs | none | — |
| 1 trust gates | 0 | early characterization for 2 and 3 |
| 2 truthful v2 | 0; content review before strict cutover | 1 and backend migration design |
| 3 durable tables | 0 | 1 and reviewed-content work in 2 |
| 4 admin/source workflows | 3 | frontend-only cleanup from 9 |
| 5 callback reconciliation | 3; collection/dashboard integration follows 4 | early image characterization |
| 6 generated contracts | stable v2 after 2; final admin API shapes after 4-5 | image/frontend work |
| 7 backend decomposition | 3-6 contracts and repositories | bounded frontend work |
| 8 media cutover | 2 and publication-attempt/reconciliation paths from 3/5 | phase 9 |
| 9 frontend growth/UI | phase 1 gates; UI convergence follows reachability cleanup | 4-8 |
| 10 corrections | 3, 5, and generated admin client from 6 | late phase 8/9 validation |
| 11 release/repo decision | all prior acceptance criteria | — |

The critical correctness path is **0 → 2 → 3 → 4/5 → 6 → 10 → 11**.
Phase 1 and the characterization portions of phases 8/9 should be taken early as
independent small PRs; UI convergence and destructive cleanup remain late.

### Wave A — immediate trust gates

#### Phase 0: Baseline, decision record, and reproducible fixtures

**Purpose:** freeze observable behavior and record the decisions that affect
both repositories.

**Backend paths:** `docs/adr/`, `docs/PIPELINE_CONTRACTS.md`,
`docs/ARCHITECTURE.md`, `tests/fixtures/`, `plans/060/`.

**Frontend paths:** `docs/adr/`, `docs/SOURCE_OF_TRUTH.md`,
`tests/fixtures/`, `src/content.config.ts`.

**Work:**

1. Write matching ADRs for durable operational state, contract generation, and
   the decision to harden the two-repo boundary before reconsidering a
   monorepo. Supersede decisions; do not rewrite historical ADRs.
2. Commit a small shared publication-contract corpus: complete v1, complete v2,
   one fixture for each missing/invalid v2 field, date edge cases, source
   objects, defaults, and additional-property rejection.
3. Capture current API/OpenAPI and publication schema snapshots as generated
   artifacts with deterministic generation commands.
4. Record the strict editorial failure report as a migration input, not a
   baseline exemption.

**Acceptance:** fixtures have explicit owners and versions; generation is
deterministic; no production behavior changes.

**STOP:** if the two repositories disagree on field meaning, settle the product
contract before generating adapters.

#### Phase 1: Close low-cost security, CI, dashboard, and docs gaps

**Purpose:** remove small high-confidence risks before invasive changes.

**Backend work:**

- In `.github/workflows/quality.yml`, pin the Gitleaks version and verify the
  publisher-provided SHA-256 checksum before extraction; install in a job-local
  path and keep least-privilege permissions.
- Correct active publication-date language in `docs/ARCHITECTURE.md` and
  `docs/PIPELINE_CONTRACTS.md`; extend doc drift checks for the invariant.

**Frontend work:**

- Add `check:search-budget`, run it after a fresh build from `test:dist`/CI, and
  test passing and oversized fixtures. Do not simply raise the 150 KiB ceiling.
- Make `check:contract-sync` and its live/snapshot workflow paths use `--strict`;
  the current strict comparison already passes.
- Replace hard-coded dashboard pass states with `unknown` until a real backend
  metric exists. Never infer schema/hero/lint success merely because another
  metric was returned.
- Correct Node 24, schema-path, image-mode, build-command, CI parity, and removed
  legacy-fallback statements in active docs. Preserve historical ADR context or
  supersede it explicitly.

**Acceptance:** checksum tampering has a failing workflow test or scripted
fixture; dashboard shows only observed states; current search artifact passes
the wired 150 KiB gate; strict contract comparison passes in both paths; doc
drift gates cover the corrected claims.

### Wave B — correctness and durable orchestration

#### Phase 2: Restore truthful schema-v2 publication

**Purpose:** make `schema_version: 2` mean that every required editorial field
is present, valid, traceable, and reviewed.

**Backend paths:** `news_collector/components/editorial/ai_editor.py`,
`news_collector/contracts/frontend_schema.py`, frontend-publication validation,
prompt/config sources, `tests/unit/editorial/`, cross-repo smoke tests.

**Frontend paths:** `src/content.config.ts`,
`scripts/check-editorial-fields.js`, `scripts/check-contract-sync.js`,
`src/content/posts/`, `tests/content-config-schema.test.ts`, content/deploy
workflows.

**Work:**

1. Characterize `EditorAgent` v2 assembly for complete, empty, partial, invalid,
   cached, and provider-failure enrichment.
2. Fail closed before writer/Git operations if a newly generated v2 artifact is
   incomplete. Persist a stable retryable editorial failure code. Do not
   silently relabel new output as v1.
3. Replace the hand-built v1 publication smoke fixture with deterministic,
   production-path v2 assembly. Prove that removing each required field makes
   backend validation and frontend consumption fail.
4. Produce a machine-readable inventory of the 30 incomplete v2 posts. For each
   post, link proposed values to verified source/editorial evidence and require
   human review. If reliable evidence does not exist, pause that record for an
   operator decision; do not invent facts and do not silently downgrade it.
5. Once the reviewed corpus reaches zero strict errors, make v2 semantic
   enforcement unconditional in the Zod collection and checker. Keep v1 only as
   an explicit legacy contract. Remove the CI/deploy bypass.

**Acceptance:** strict audit reports zero; new partial v2 output cannot reach a
publication branch; both CI pipelines fail a partial fixture and pass a complete
one; the content migration has a review record.

**Rollback:** revert enforcement and content commits together only if the
producer cannot publish; never leave CI permissive while producers claim v2.

**STOP:** no verified evidence for a historical post; material disagreement
about required field meaning; or product owner asks Stage 4 to remain
non-blocking. These require an explicit version/fallback decision.

#### Phase 3: Add durable lifecycle tables and compatibility projections

**Purpose:** establish persistent, queryable workflow evidence without breaking
existing readers.

**Backend paths:** `news_collector/storage/models.py`, new narrowly named
repositories, `alembic/versions/`, `tests/test_database_migrations.py`, article
repository transition tests.

**Work:**

1. Add `workflow_runs`, `workflow_stage_attempts`, `editorial_decisions`,
   `publication_attempts`, and `publication_events` in one or two additive
   Alembic revisions extending current head `b61c2d3e4f50`.
2. Add check constraints, foreign keys, lookup indexes, unique delivery keys,
   and the SQLite partial unique index that enforces one active collection.
3. Add typed repositories with compare-and-set transitions and append-only
   attempt/decision methods. Do not expose new cross-package `dict[str, Any]`
   APIs.
4. Backfill publication/audit history from current `Article` fields/JSON using a
   deterministic, idempotent migration or explicit one-shot command. Preserve
   unknown legacy values rather than guessing.
5. Dual-write existing article state and new records through repository methods.
   Add consistency assertions and a read-only reconciliation report.

**Acceptance:** fresh and legacy DBs migrate to a single head; repeated upgrade
is safe; downgrade round trip is proven where governance requires it; existing
API behavior remains green; consistency report is clean on fixtures.

**Rollback:** code can return to legacy readers while additive tables remain.
Do not drop tables or legacy columns in this program.

#### Phase 4: Make admin collection and source mutation real workflows

**Purpose:** fix the two concrete workflow defects in `serving/api.py` and thin
the HTTP layer along proven seams.

**Backend work:**

1. Add `CollectionRunWorkflow` under `news_collector/logic/workflows/`. It
   creates the durable row, handles the single-flight conflict, dispatches the
   runner, heartbeats, records the summary/error, and recovers expired leases.
2. Change status lookup so a named unknown ID is 404. Add terminal-only 90-day
   retention and tests that active rows are never pruned.
3. Add `SourceCatalogWorkflow` that loads a fresh YAML snapshot under a
   documented process/file lock, validates the full candidate catalog, writes
   a same-filesystem temporary file and `os.replace`, synchronizes SQLite, and
   restores the prior YAML if DB sync fails. If compensation fails, persist and
   surface a reconciliation-required state.
4. Batch source circuit-state lookup in `SourceRepository` and have the list
   route compose one catalog read plus one DB query.
5. Keep auth, request parsing, response models, and HTTP exception mapping in
   `serving/`; move no new workflow logic there.

**Acceptance:** concurrent collect requests yield one 202 and one typed 409;
restart recovery is deterministic; exact unknown lookup is 404; YAML/DB failure
injection cannot silently diverge; source listing statement count is bounded.

**STOP:** if deployment can run multiple writers and no robust file lock is
available, define/enforce a single-writer deployment or move catalog mutations
through a Git-backed write path before enabling the editor.

#### Phase 5: Persist and reconcile publication callbacks

**Purpose:** close the state gap between PR creation, frontend deployment, and
backend acknowledgement.

**Backend paths:** webhook contracts/handler, `serving/api.py`, publication
repositories, `PROrchestrator` recovery entry points, admin API.

**Frontend paths:** `scripts/post-publish-callback.js`, deploy workflow, callback
tests, admin dashboard.

**Work:**

1. Add a versioned delivery/idempotency ID to callback envelopes. Frontend sends
   bounded retries with exponential backoff and emits a diagnostic artifact on
   failure; deployment stays non-blocking.
2. Backend authenticates/validates, persists the receipt, then processes it.
   Duplicate delivery returns the stored result without reapplying transitions.
3. Map validation and publish-complete events to legal
   `publication_attempts` transitions. Processing exceptions update the event
   to retryable/failed and remain operator-visible.
4. Add a scheduled/manual reconciler for stale `pr_created`/`deployed` attempts.
   It may query GitHub/deployment evidence and replay stored events. It must not
   create duplicate PRs or mark published without deployment evidence.
5. Drive dashboard schema, validation, hero/image, callback, and publication
   health from real attempt/event/check records. Missing evidence is `unknown`,
   not pass.

**Acceptance:** lost callback, duplicate callback, out-of-order callback,
backend restart, processing exception, and stale open PR all have integration
tests; every fixture reaches a truthful terminal or actionable state; no
duplicate PR is created.

### Wave C — typed boundaries and smaller modules

#### Phase 6: Generate admin and publication contracts

**Purpose:** remove handwritten cross-language drift without creating a second
source of truth.

**Admin contract:**

1. Generate deterministic OpenAPI from `create_app(...).openapi()` using FastAPI
   and Pydantic's native schema APIs.
2. Pin `openapi-typescript` and use `openapi-fetch` in `apps/admin`; enable
   `noUncheckedIndexedAccess`. Replace handwritten response mirrors and unsafe
   casts incrementally, endpoint group by endpoint group.
3. CI regenerates the OpenAPI document and TypeScript artifact and fails on a
   diff. No live backend is required to build the admin.

**Publication contract:**

1. Refactor frontend schema into an exported JSON-compatible structural schema
   and an Astro collection schema that adds date coercion and semantic v2
   refinements.
2. Use stable Zod 4 `z.toJSONSchema` to generate a committed neutral artifact.
   Handle dates explicitly and fail generation for unrepresentable constructs;
   never use `unrepresentable: "any"` and do not use experimental
   `z.fromJSONSchema`.
3. Backend validates against the generated artifact and its typed Pydantic
   model. Run the shared valid/invalid corpus through Zod, JSON Schema, and
   Pydantic; allowed divergences must be named and tested.
4. Keep the existing strict parser during the cutover. Delete the regex parser
   and old snapshot only after byte-for-byte generation and corpus parity have
   passed for a full release window.

**Acceptance:** changing a Pydantic admin model yields a required generated
client diff; changing the Zod structural schema yields a required JSON Schema
diff; both repositories reject the same invalid corpus; generation is stable on
two consecutive runs.

**STOP:** any generated artifact loses a semantic constraint or changes accepted
content unintentionally. Keep the old strict gate until parity is explained.

#### Phase 7: Extract concrete backend workflows and editorial stages

**Purpose:** reduce concentration while preserving stable public APIs.

**Refinery work:** retain `RefineryEngine.process_articles(...)` and
`process_single_article(...)`. Extract only remaining seams:

- a typed publication-attempt recorder backed by phase 3;
- a target-repository publication workflow that composes the already extracted
  identity, writer, image, and PR collaborators;
- audit scheduling/recording where it is independently testable.

**Editor work:** retain `EditorAgent.process_article(...) -> str` as a façade.
Extract typed stages for normalized input, translated draft,
adapted/critic-approved draft, enrichment result, and final publication
artifact. Each stage declares input/output, cache identity, retry policy,
provider/model provenance, and failure code. Do not rewrite prompts or editorial
policy during extraction.

**Admin work:** after phase 4 characterization, split route registration from
`create_app` by bounded domain routers. Routes still own HTTP only; workflows
and repositories remain framework-free.

**Acceptance:** existing regression suites pass unchanged before new assertions;
fixtures prove identical Markdown, branch/PR behavior, and admin wire responses;
complexity moves to named, single-purpose modules rather than generic base
classes.

**STOP:** snapshot/output drift not explained by an intentional contract change;
new circular dependencies; or an abstraction has only a speculative consumer.

### Wave D — publication assets and frontend growth

#### Phase 8: Move media finalization out of ordinary frontend builds

**Purpose:** make image publication idempotent, testable, and proportional to
changed assets.

**Frontend work first:**

1. Extract `publish-image-derivatives.js` into importable functions with injected
   filesystem, Sharp, and S3 boundaries; retain a thin CLI main guard.
2. Characterize unchanged, changed, missing-remote, upload-failure,
   conversion-failure, manifest-removal, and GitHub/R2 mode behavior.
3. Reuse manifest entries when content hash, variant policy/version, and public
   base URL match. Use bounded concurrency. Provide explicit periodic/full
   reconciliation to detect externally deleted objects.

**Cross-repo cutover:**

4. Define a versioned article-owned media descriptor from the existing fields:
   original dimensions/hash plus variant width/height/format/object key/URL.
5. Have backend publication finalize/upload the hero and submit the descriptor or
   manifest delta in the same content PR. Add a concrete `media_assets` table
   only if it is required for retries/reconciliation; otherwise keep the typed
   descriptor with the publication attempt.
6. Remove the publisher from `npm run build` only after backend publication and
   explicit reconciliation produce parity. Keep frontend build and
   `check:image-derivatives` read-only. Retire the sync workflow only after one
   release window.

**Acceptance:** unchanged builds perform no R2 mutation; changed assets upload
once; remote deletion is found by reconciliation; `Image.astro` output and local
fallback remain stable; no broken image at 375px/1280px.

#### Phase 9: Bound frontend growth and converge the live UI deliberately

**Purpose:** remove dead surface and avoid archive-size build regressions before
changing UI governance.

**Work:**

1. Fix reachability allowlist matching to use repository-relative paths. Review
   the 37 current results in small cohorts, prove no MDX/dynamic consumer, delete
   only genuinely dead components, and then wire the checker into CI. Do not
   bulk allowlist.
2. Characterize related-post scoring and tie order. Build category/tag indexes
   once and cache deterministic top-four results per post; preserve observable
   rankings.
3. Remove verified-unused `@iconify-json/flat-color-icons`, `astro-embed`,
   `@types/glob`, and `ts-node`, including unused icon config. Reintroduce only
   with a real consumer.
4. After dead-code removal, inventory live `template` callers. Migrate route-sized
   surfaces into `ds` or `common`, preserving metadata and shared `Image`
   behavior. `ds` must never import `template` during transition.
5. When no production `template` consumer remains, create a superseding ADR and
   update AGENTS/SOURCE_OF_TRUTH/ARCHITECTURE before removing the layer/freeze
   guard. Until then the accepted two-layer law remains binding.

**Acceptance:** reachability gate is green and enforced; related-post golden
fixtures are unchanged; build timing is measured before/after; full Astro,
content, dist, browser, accessibility, metadata, and 375px/1280px checks pass;
one live design-system ownership model is documented only when true.

### Wave E — editorial feedback and final simplification

#### Phase 10: Integrate the reader correction lifecycle

**Purpose:** turn durable intake into a traceable editorial correction loop.

**Contract:** implement plan 047's versioned `ReportEnvelope` and eight states:
`received`, `triaged`, `duplicate`, `rejected`, `accepted`,
`correction_proposed`, `correction_published`, `closed`.

**Work:**

1. Resolve `refinery_id` and content revision server-side from the public URL;
   never trust reader-supplied identity.
2. Add `reader_reports` and append-only `reader_report_events` in SQLite for the
   redacted envelope, state, resolved identities, idempotency key, and lifecycle
   evidence. Keep contact only in the private intake object referenced by an
   opaque object key; never copy it to logs or decision history. Delete or
   redact that object on closure according to the retention contract.
3. Add idempotent intake/reconciliation from the Worker object to those backend
   report records and append-only `editorial_decisions`. Do not add a queue
   platform; the existing low-volume Worker/R2 path is sufficient.
4. Add admin triage, duplicate/reject/accept, proposed correction, publication
   linking, and closure actions with legal transitions and audit events.
5. Link the correction publication attempt and frontend deployment callback to
   `correction_published`; close only after deployment evidence and operator
   action.

**Acceptance:** transition, idempotency, privacy deletion, forged identity,
duplicate, rejected, corrected, and closure paths pass; a correction can be
traced from report ID to content revision and deploy without exposing contact.

#### Phase 11: Consolidate gates, reconcile active docs, and decide repository shape

**Purpose:** finish the program with one reproducible release proof and a measured
repository-boundary decision.

**Work:**

1. Consolidate duplicated workflow steps behind repository-owned scripts/Make
   targets while keeping repository-specific jobs. Do not create a third CI
   orchestrator merely to reduce YAML.
2. Add a cross-repo release smoke that starts from deterministic complete-v2
   assembly, validates the generated publication contract, exercises the
   publish-attempt/callback cycle, builds Astro, and checks the deployed artifact
   shape without external side effects.
3. Update all active architecture, pipeline-contract, source-of-truth, README,
   contributing, and operations docs. Preserve historical archives/ADRs and
   supersede them where appropriate.
4. Measure remaining two-repo costs over at least one release window: duplicated
   dependency installs, cross-repo PR count, contract-drift incidents, callback
   reconciliation incidents, build/deploy duration, and ownership friction.
5. Write a decision ADR:
   - **Keep split** if generated contracts and durable reconciliation make the
     boundary reliable with low overhead.
   - **Move to a workspace/monorepo** only if measured coordination cost remains
     material and one atomic change/test graph clearly reduces it. The migration
     then becomes a separate plan with rollback and deployment ownership.

**Acceptance:** all program gates pass from clean checkouts; docs match code;
operators can diagnose every nonterminal workflow from persisted data; the repo
decision is evidence-based and does not block the correctness phases.

## Verification matrix

Commands below are **declared**, not claimed as executed by this planning pass,
unless listed in the planning evidence section.

| Change class | Targeted proof | Required broader proof |
|---|---|---|
| Backend models/migrations | `pytest tests/test_database_migrations.py -q` plus new repository tests | `make lint && make type && make test && make test-boundaries` |
| Admin API/workflows | `pytest tests/test_serving_admin_api.py -q`; restart/concurrency/failure-injection tests | `make admin-test && make admin-build && make verify-ci` |
| Refinery/editor | `pytest tests/decompose_refinery -q`; editor/enrichment/guardrail suites | `make test-contracts && make quality-gate && make verify-ci` |
| Backend docs/plans | `make docs-check && make config-docs-check && make plans-ledger-check` | `make verify-ci` when executable contracts change |
| Frontend content/contract | strict editorial check; content schema and contract-sync tests | `npm run lint && npm run validate:content` |
| Frontend code/config/deps | targeted Vitest/Playwright tests | `npm run build && npm run test:dist && npm run test:audit` |
| Frontend visual/interaction | relevant browser test | manual 375px and 1280px, no console errors/broken images/canonical drift |
| Worker/report intake | Worker unit/integration tests in workerd | frontend `npm run verify:ci` equivalent |
| Cross-repo release | generated-contract corpus + publication callback E2E fixture | both repositories' full required gates from clean checkout |

Before a non-disposable backend DB migration, follow the repository's explicit
operator sequence:

```bash
python scripts/check_migration_revision.py
python scripts/migrate.py up
```

## Observability and operator runbooks

Before cutting over readers, add:

- counts and ages of queued/running/interrupted workflow runs;
- stage-attempt failure counts by stable error code, not raw exception text;
- publication attempts by state and age;
- callback receipts pending/failed/duplicate and oldest age;
- source catalog reconciliation state;
- correction reports by nonterminal state and age;
- image reconciliation failures and missing object count.

Runbooks must cover stale collection lease, YAML/DB compensation failure,
stalled PR, missed callback, invalid v2 backfill, missing derivative, and privacy
deletion failure. Never place tokens, reader contact, full article content, or
LLM prompts in operational logs.

## Rollout and rollback rules

1. **Expand → dual-write → compare → cut over → clean up.** Every DB/contract
   change follows this order.
2. Feature flags, where necessary, choose readers—not truth. Do not maintain two
   independently mutable sources of truth.
3. Roll back application readers before destructive schema cleanup. This plan
   contains no legacy-column or table drops.
4. Generated artifacts change in the same PR as their source and generation
   command; CI must fail stale output.
5. Cross-repo changes land producer-compatible first, consumer strictness last,
   except where a coordinated PR pair is explicitly held until both are green.
6. Deploy failures never cause duplicate publication. Reconciliation inspects
   durable state and external evidence before retrying a side effect.

## Program-wide STOP conditions

Stop the affected phase and request an explicit decision if:

- editorial data would need to be invented to satisfy v2;
- generated schemas accept/reject materially different content without an
  explained, tested compatibility rule;
- a migration has multiple heads, loses existing state, or cannot be rolled
  back as required;
- single-flight cannot be guaranteed under the actual deployment topology;
- a callback retry or recovery path can create a duplicate PR/publication;
- source catalog rollback fails without a durable reconciliation signal;
- an extraction changes rendered Markdown, scoring/editorial policy, or public
  HTTP behavior outside the approved contract;
- media cutover can produce content that references an unattested derivative;
- a component marked unreachable has an unmodeled dynamic/MDX consumer;
- privacy requirements for reader contact cannot be enforced;
- repository consolidation is proposed without measured post-hardening cost.

## Out of scope

- PostgreSQL, Redis, Kafka, Celery, or a distributed workflow platform.
- A big-bang monorepo move or framework/language rewrite.
- Replacing Git pull requests and human editorial approval with direct publish.
- A public CMS, live collection runtime, or client-side application framework.
- Rewriting editorial prompts/policy while extracting stages.
- Fabricating historical editorial metadata or silently downgrading claimed v2
  posts.
- Removing legacy DB state before compatibility and reconciliation prove the new
  model.
- Replacing R2, GitHub Pages, Astro, FastAPI, SQLAlchemy, or SQLite without a
  separate evidence-backed plan.

## Done criteria

- [ ] All 31 current v2 posts pass strict validation with review evidence, and
      new incomplete v2 output fails before publication.
- [ ] Admin collection state survives restart, is transactionally single-flight,
      retains active history, and returns 404 for unknown named runs.
- [ ] Source YAML/SQLite mutation is atomic or visibly reconcilable; source
      listing has no per-row DB lookup.
- [ ] Workflow runs, stage attempts, editorial decisions, publication attempts,
      and callback events are persistent, typed, queryable, and covered by
      migration tests.
- [ ] Missed/duplicate/out-of-order callbacks reconcile without duplicate PRs or
      false published states.
- [ ] Astro admin types/client are generated from FastAPI OpenAPI and stale
      artifacts fail CI.
- [ ] Publication JSON Schema is generated from the frontend structural Zod
      schema, and Zod/JSON Schema/Pydantic pass a shared parity corpus.
- [ ] `serving/api.py`, `RefineryEngine`, and `EditorAgent` retain stable façades
      while concrete workflows/stages move to tested modules.
- [ ] Ordinary frontend builds are read-only with respect to R2; image publication
      is incremental, bounded, attested, and reconcilable.
- [ ] Search budget and component reachability gates are enforced; 37-item dead
      inventory is resolved; related-post ranking is deterministic and bounded;
      verified-unused dependencies are removed.
- [ ] UI ownership reflects actual live components, with a superseding ADR only
      after the template layer has no production consumer.
- [ ] Reader reports complete the approved privacy-preserving correction
      lifecycle and link to the published revision.
- [ ] Security checksum, dashboard evidence, active docs, and CI claims match
      code.
- [ ] Both repositories pass their full required gates and the cross-repo release
      smoke from clean checkouts.
- [ ] The final repository-shape ADR is based on measured post-hardening evidence.

## Planning evidence (executed 2026-08-22)

- Backend and frontend repository status/head inspection: backend `d63cbea`,
  frontend `237cd13`; frontend had a pre-existing `.codegraph/.gitignore`
  modification which this plan does not touch.
- `STRICT_EDITORIAL=true node scripts/check-editorial-fields.js --json`:
  expected current failure, 31 v2 posts, 30 failing posts, 180 errors.
- Strict cross-repo contract comparison: current schemas pass with the documented
  date divergence.
- Component reachability: 37 unreachable components.
- Current built search artifact: 97,668-byte gzip payload under 150 KiB; artifact
  freshness was not independently established by a new build.
- Zod 4.4.3 local API probe: `z.toJSONSchema` is available. Date/refinement
  representation limitations were verified and drive the structural/runtime
  schema split above.

No lint, build, full test, migration, network deployment, R2 reconciliation, or
content mutation was executed while creating this plan.

## Execution record

Not started. Update after every merged phase with repository SHAs, PR links,
commands actually run, outcomes, exceptions, and remaining rollback window.
