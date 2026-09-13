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
4. Export remains a supported boundary for the legacy Streamlit path.
   `ExportContractV2` is the preferred contract, but the collector CLI's
   `--export-json` still serializes a V1 artifact; legacy Refinery handles it.
   Export absence is therefore not a universal explanation for an empty admin.

## Publication orchestration

The current API dispatches `PublicationRunWorkflow`, which records execution
in `workflow_runs` and invokes the editorial/publication workflow. It accepts
exactly one article ID or URL. See `docs/PIPELINE_CONTRACTS.md` for status,
conflict and lease-recovery semantics.

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
| Publication stops before PR | Workflow error, editorial result, image artifact and GitHub configuration |
| PR validation fails | Frontend diagnostic and exact render schema |
| Deployed article remains pending in backend | Callback IDs/transport and the backend's effective database |

Use [PIPELINE_CONTRACTS.md](PIPELINE_CONTRACTS.md) for contracts,
[ARCHITECTURE.md](ARCHITECTURE.md) for boundaries,
[RUNBOOK_LOCAL_DEV.md](RUNBOOK_LOCAL_DEV.md) for setup and
[runbook.md](runbook.md) for incidents. Historical plans do not override those
active sources or the files that implement the behavior.
