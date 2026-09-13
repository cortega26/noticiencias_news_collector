# Phase 0 — Evidence, APIs and baseline

Documentation discovery completed for planning on 2026-09-04. Reconcile these
facts with the checkout before implementing; no dependencies were installed and
no runtime tests were run to produce this plan.

## Repository evidence to read

| Existing source | Relevant evidence/pattern |
| --- | --- |
| `plans/archive/078-startup-less-lease-recovery/spec.md` | A fresh running row can have NULL heartbeat; `start()` excludes queued recovery. |
| `news_collector/logic/workflows/collection_run_workflow.py` | `CollectionRunWorkflow.start(dry_run=...)`, recovery and state-based CAS. |
| `news_collector/logic/workflows/publication_run_workflow.py` | `PublicationRunWorkflow.start(article_id=..., article_url=...)`; publication uses daemon dispatch and lifecycle rows. |
| `tests/unit/logic/workflows/test_collection_run_workflow.py` | SQLite manager fixture, no-op dispatch, direct transition/heartbeat tests. |
| `tests/unit/logic/workflows/test_publication_run_workflow.py` | Matching publication tests and Plan 078 regression examples. |
| `tests/conftest.py` | `NEWS_COLLECTOR_TEST_MODE` set before package imports; database cleanup. |
| `pyproject.toml`, `requirements-security.lock` | Hypothesis already declared and locked; pytest has a global 10-second timeout. |
| `news_collector/serving/api.py`, `news_collector/contracts/admin.py` | `create_app(database_manager=None)` accepts an explicit manager; four target routes already declare 409/404 models. |
| `apps/admin/src/lib/types.ts`, `api.ts`, `api.test.ts` | Four manually mirrored workflow responses and existing HTTP/error handling. |
| `tests/test_serving_admin_api.py` | Real SQLite plus FastAPI test client patterns; actual route behavior. |
| `plans/060/spec.md`, Phase 6 | Parent plan for generated contracts; broader work remains outside this pilot. |
| `scripts/quality_gate.py`, `quality_gate/golden/` | Deterministic snapshot checks and existing input/output/expectation triplets. |
| `scripts/quality_gate_refresh.py` | Live editor invocation example only; running it is not part of this plan. |
| `tests/data/enrichment_eval.jsonl`, `scripts/evaluate_enrichment_registry.py` | Classification benchmark, not generated-article factuality benchmark. |
| `news_collector/utils/metrics.py`, `news_collector/observability/enrichment_metrics_store.py` | Multiple existing telemetry surfaces; do not infer all metrics are in-memory. |
| `Makefile`, `.github/workflows/ci.yml`, `.github/workflows/quality.yml`, `docs/ci.md` | Existing gates and dependency provisioning. |
| `scripts/sync_lockfiles.py`, `plans/README.md` | Lockfile ownership and existing technology decisions. |

Inspect relevant source with CodeGraph first. If a result omits the requested
body, obtain the omitted source; do not infer implementation from symbol names
or unrelated generated Worker declarations.

## Allowed third-party APIs

Read the linked sections. These APIs were verified in official documentation;
package compatibility still needs to be tested when pinning dependencies.

| Tool | Supported surface | Source |
| --- | --- | --- |
| Hypothesis | `RuleBasedStateMachine`, `rule`, `precondition`, `invariant`, `teardown`, `Machine.TestCase`; `settings(max_examples=..., stateful_step_count=..., deadline=None)` | [Stateful testing](https://hypothesis.readthedocs.io/en/latest/stateful.html), [settings and fixture lifecycle](https://hypothesis.readthedocs.io/en/latest/reference/api.html) |
| FastAPI | `app.openapi()`; `responses={409: {"model": Model}}` documents additional bodies | [Schema generation](https://fastapi.tiangolo.com/how-to/extending-openapi/), [additional responses](https://fastapi.tiangolo.com/advanced/additional-responses/), [lifespan](https://fastapi.tiangolo.com/advanced/events/) |
| openapi-typescript | `openapi-typescript input.json --output output.d.ts`; add `--check` to detect stale generated types; `components["schemas"]["ActualName"]` | [CLI](https://openapi-ts.dev/cli), [basic usage](https://openapi-ts.dev/introduction) |
| Promptfoo | `echo` provider; rendered `{{logged_output}}` prompt; `get_assert(output, context)` Python assertion returning `{pass, score, reason}` | [Echo/replay](https://www.promptfoo.dev/docs/providers/echo/), [Python assertions](https://www.promptfoo.dev/docs/configuration/expected-outputs/python/) |
| Promptfoo CLI | `validate -c config.yaml`; `eval -c config.yaml --max-concurrency 1 --no-cache --no-share -o results.json` | [CLI flags and exit codes](https://www.promptfoo.dev/docs/usage/command-line/) |

Do not copy illustrative schema names from documentation. Inspect actual
generated declarations. TypeScript generation is not runtime validation; an
OpenAPI response declaration does not enforce an exception's actual JSON body.
The Promptfoo echo documentation includes model-based grading examples: use
deterministic assertions here so the whole evaluation remains offline.

## Execution preflight

Create `tests/baseline.md` under this plan when implementation starts. Record:

- Backend and frontend commit IDs, dirty file list, Python/Node versions.
- Assigned phase, intended files, docs read, exact resolved dependency versions
  when a phase adds them. Keep Python 3.13 and Node 24 repository conventions.
- Result of the phase's targeted checks before changes and existing failures.
- Whether concurrent work affects a target file. Re-read that file before editing.

Existing useful commands (News Collector root):

```bash
git status --short
git rev-parse HEAD
.venv/bin/python --version
node --version
.venv/bin/python scripts/validate_plans_ledger.py
.venv/bin/python -m pytest tests/unit/logic/workflows/test_collection_run_workflow.py tests/unit/logic/workflows/test_publication_run_workflow.py --no-cov -q
```

Do not run `make bootstrap`, installation or live provider commands merely to
write a baseline report. If implementation needs missing dependencies, use the
normal repository provisioning workflow and applicable environment permissions.

## Gate

Proceed when relevant files and supported APIs have been read, no conflicting
task is being overwritten, and failures are recorded honestly. If a completed
implementation already exists, verify it and remove that task from the plan;
do not build a second version.
