# Product flow

Status: Active. Subordinate to `docs/SOURCE_OF_TRUTH.md` and `docs/AGENTS.md`.

The backend discovers and prepares articles; the sibling frontend renders and
deploys them. This is a navigation guide to current code, not a promise that
every article follows every optional stage.

## From source to editorial candidate

1. `scripts/run_collector.py` bootstraps collection; collectors and enrichment
   integrations fetch source material under `news_collector/collectors/`,
   `news_collector/enrichment/` and `news_collector/infrastructure/`.
2. System/workflow code composes validation, scoring, taxonomy, ranking and
   storage. Models in `news_collector/storage/models.py` persist candidates
   in the configured SQLite database. Alembic owns schema changes.
3. The current Astro admin (`apps/admin/`, `make admin`) reads candidates and
   dispatches operations through the authenticated API. It does not require
   the operator to manually produce an export file first.
   Freshly collected articles stay at `processing_status='validated'` until
   scoring commits a row, so the triage queue exposes a `validated`
   ("Recolectadas") filter for that intake window — a scoring backlog is
   visible instead of silent. Scoring persists in bounded sub-batches, so an
   interrupted run keeps the scores it already committed.
4. Collection runs are durable in `workflow_runs`: a run whose worker process
   died (dev-server reload, crash) is recovered to `interrupted` as soon as
   the next process starts, instead of blocking new runs until the lease
   timeout. A conflict response reports the active run, and the admin banner
   shows the terminal state and error detail. While running, `/triage` reports
   the current backend phase and step from the same run metadata, plus elapsed
   time, progress-update age and worker-heartbeat age. Normal collection has
   six phases; dry runs omit the export phase. Collection progress has no ETA.
5. Export remains a supported boundary for the legacy Streamlit path.
   `ExportContractV2` is the preferred contract, but the collector CLI's
   `--export-json` still serializes a V1 artifact; legacy Refinery handles it.
   Export absence is therefore not a universal explanation for an empty admin.

## Publication orchestration

The current API dispatches `PublicationRunWorkflow`, which records execution
in `workflow_runs` and invokes the editorial/publication workflow. It accepts
exactly one article ID or URL. See `docs/PIPELINE_CONTRACTS.md` for status,
conflict and lease-recovery semantics.

While a run is queued/running, `GET /v1/admin/publish/status` also exposes
advisory live progress for the admin GUI: the current one of six overview
phases, the active backend step, completed Refinery stages, and the article's
position in a batch. A new batch item clears the previous item's active step.
The status includes separate progress-update and worker-heartbeat timestamps.
The ETA is an orientative whole-run estimate based on the historical median
duration of successful single-article runs. Progress is observability only —
recording it (or failing to) can never block or change a publication.

Frontend acknowledgments (`publish_complete`) are delivered to the hosted
serving instance, which keeps them as durable receipts; the local operator
pulls them into the production DB (`make webhooks-pull`, ADR-0011), the only
place `published_at`/`published_url` are set. Until a delivery is pulled, a
live article can still appear as `publishing` locally — convergence is
eventual by design.

Editorial preparation completes before image resolution (plan 190).
`EditorAgent.prepare_article()` returns a sealed `EditorialDraft` containing
validated editorial frontmatter, body, sources, critic verdict and grounding
notes. The draft has no image and is internal to the backend. The workflow
persists it with the original source snapshot, canonical identity and editorial
fingerprint in `workflow_runs.run_metadata` through the checkpoint repository.
It never sends an incomplete Markdown post to the frontend.

Missing images, placeholders, failed downloads and unproven redistribution
rights create or retain an image brief. They park the publication run in
`waiting_for_image` after saving editorial work; editorial rejection remains a
failure. Waiting releases the global publication slot, has no heartbeat or
completion timestamp, and does not prevent the next article or batch item from
being processed. The admin shows **Edición completada · esperando imagen** with
the reason and a link to the brief, without an execution ETA or stall warning.
Plan 190 supersedes plan 168's pre-dispatch `409 image_required` gate: a pending
brief no longer prevents editorial dispatch.

Hero resolution (`news_collector/logic/workflows/image_handler.py`) prefers a
staged editorial asset. A local path alone does not prove reuse rights. Remote
source images remain subject to `REMOTE_IMAGE_ALLOWLIST` (empty by default);
a blocked source image queues `third_party_image_blocked`, and an unverified
local path queues `unproven_image_rights`. Staged assets require approved origin
(`ai_generated`, `licensed` or `original`), successful decoding and matching
asset evidence to release the image dependency. `unknown` remains readable for
legacy briefs but cannot release a wait. The existing allowlisted remote-image
download path remains supported; host approval is an explicit reuse policy.
Final assembly supplies usable Spanish alt text, with a headline fallback when
the supplied description is boilerplate.

The Images desk exposes the stored `generated_prompt` and its copy button.
During an active Codex session, Codex can use the built-in `imagegen` tool,
review the result for scientific accuracy and cover composition, and upload it
with `image_origin=ai_generated`. This is a session tool workflow, not an
unattended image-generation API or a new paid provider integration. Generation
failure leaves the image task pending and preserves the editorial draft.
Uploads can include typed `generation_metadata` (prompt, tool, SHA-256, width
and height); the server checks the hash and dimensions against the decoded
file and records asset evidence. Pillow 13.0.0, previously in the Refinery lock,
is now also pinned in the base runtime lock so serving can decode actual image
bytes without installing the Streamlit extra.

The serving process reconciles ready requests at startup, after an approved
image is registered, after worker completion and every 15 seconds. It resumes
the same durable request when the single-flight slot is free. Recovery reads
the saved source snapshot even if the current candidate export no longer
contains the article. An unchanged editorial fingerprint reuses the draft
without repeating editorial LLM calls; changing source/editorial inputs,
models, prompts or policy invalidates it, whereas media-only changes do not.
Successful and failed batch siblings keep their recorded outcomes.

Once media is ready, `EditorAgent.assemble_article()` validates the complete
artifact against `AstroPost` before the normal write, frontend checks and PR
steps. Publishing an `ai_generated` brief prefixes the alt exactly once with
`Ilustración generada con IA: `; the frontend uses `image_alt` for its visible
hero caption. Other origins leave alt text untouched.

`news_collector/logic/workflows/refinery_engine.py` coordinates editorial
processing, image/policy checks, target-repo writing and GitHub publication.
The target artifact is Markdown under `src/content/posts/<canonical-slug>.md`
in the sibling frontend, with `refinery_manifest.json` identity recovery.

The backend mirror `news_collector/contracts/frontend_schema.py` must agree
with the frontend authority `../noticiencias/src/content.config.ts`. The
frontend checker used by both repositories checks more than field names:
it compares types, constraints and optionality with documented divergences.
Current v2 posts require the six enrichment fields unconditionally; schema
and validation code own exact requirements.

Publication must preserve canonical identity, use an intentional date, supply
image alt text and one primary editorial category, and avoid permalink
collisions. `Editorial` is reserved for first-party content. Missing source
and collection dates fail with `UndatedArticleError`; no current-clock fallback
creates a new identity.

## PR, deployment and acknowledgment

The publisher opens a frontend PR and records `PR_CREATED`. This is distinct
from scoring status `completed`, workflow execution success and a live URL.
Optional post-PR auditing records metadata; it does not replace pre-PR checks.

Frontend `../noticiencias/.github/workflows/content-guard.yml` owns PR validation. Its checks
include content/schema validation, build/dist tests and other workflow-specific
gates. Deployment is owned by `../noticiencias/.github/workflows/deploy.yml`, which builds,
deploys to GitHub Pages and performs post-deploy checks. Branch protection and
actual runtime availability must be verified in the hosting environment.

With webhook URL/token configured, Content Guard can send validation failures;
the deployment workflow can acknowledge publication. The backend authenticates
`POST /api/v1/webhook/frontend` and updates matching publication attempts using
explicit `publication_ids`. No IDs means no inferred article transition.
Notifications are best-effort, so missing acknowledgment can leave backend
state stale after a successful frontend deployment.

## Failure diagnosis

| Symptom | First evidence to inspect |
| --- | --- |
| No admin candidates | Effective database, source/run results and current API filters |
| Start returns conflict | Active run ID, type, heartbeat and lease age |
| Identity cannot be resolved | Persisted slug, manifest/frontend artifact, source/collection dates |
| Editing is complete but no PR exists | `waiting_for_image`, image brief reason and approved asset evidence; this is a dependency wait |
| Publication fails before PR | Workflow error, editorial result and GitHub configuration |
| Publication seems hung | Live progress stages, heartbeat age and lease age in the admin publish status |
| PR validation fails | Frontend diagnostic and exact render schema |
| Deployed article remains pending in backend | Callback IDs/transport and the backend's effective database |

Use [PIPELINE_CONTRACTS.md](PIPELINE_CONTRACTS.md) for contracts,
[ARCHITECTURE.md](ARCHITECTURE.md) for boundaries,
[RUNBOOK_LOCAL_DEV.md](RUNBOOK_LOCAL_DEV.md) for setup and
[runbook.md](runbook.md) for incidents. Historical plans do not override those
active sources or the files that implement the behavior.

### Evidence-first editorial review (plan 191)

The editor builds an internal brief from the source text already retrieved by
collection: reader question, proposed explanatory contribution, exact bounded
passage, source URL/hash and coverage limitations. It performs no additional
retrieval and does not claim that the available news source is independent or
primary evidence. Adaptation, proofreading, headline and enrichment callers
receive this context. Source-support comparison preserves uncertainty; it is
not an independent fact check.

Material unsupported claims and close paraphrase surviving bounded repair hold
publication; persistent unsupported/sensationalist headlines also hold it.
Infrastructure and skipped reviews remain explicitly unverified, never cached
as successful review. Stage artifacts preserve work for correction. Versioned,
source/prompt-bound stage caches and candidate-bound critic checkpoints prevent
old approvals from silently covering changed editorial inputs.

Article PRs are created as **drafts** with available evidence, actual critic
findings, image provenance, final artifact fingerprint and a human review
checklist. Human review remains **pending** until the editor reviews the final
headline, body and metadata. Changes to the final commit/evidence need renewed
review. No human reviewer metadata is generated. This implementation does not
change GitHub protected settings; a draft/checklist alone cannot enforce human
approval against an operator who marks a PR ready and merges it.

Known material or headline fidelity/sensationalism findings remain held through
failed/malformed re-review and regeneration. Candidate changes (including a
technical repair on resume) require explicit material revalidation within the
same article/source/prompt revision; only positive checkpoints require exact
body equality. Concrete findings and reviewed/latest-candidate hashes remain
in isolated review artifacts, and unverified infrastructure never clears a
known rejection. A new article/source/prompt revision starts a separate review.
