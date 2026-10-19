# scripts/ — entrypoint index

**Status:** Active

This directory holds operator CLIs, CI gates, diagnostics, benchmarks and
historical one-offs. It is not a stable library API: scripts may change or be
deleted between releases. Prefer the `make` target that wraps a script when one
exists (`make help` lists them).

## How to find things

1. Search this page for the task, not the script name.
2. Scripts referenced by the Makefile, `.github/workflows/`, or the active docs
   are listed individually with their caller.
3. Anything under [One-off / historical](#one-off--historical) is not called by
   a gate or supported workflow. Read its header before running it, and never
   point it at production data.
4. Add new scripts to this index in the same PR that adds them.

`scripts/audit.coveragerc` is the coverage configuration used by
`make test-audit`; `scripts/__init__.py` makes `scripts` importable for tests.
Neither is an entrypoint.

## Collector, pipeline and serving

| Script | Invoked by | What it does |
|---|---|---|
| `scripts/run_collector.py` | `make run-local`, `ci.yml` e2e, `daily_collector.yml` | Primary collector CLI: `--dry-run`, `--sources`, `--healthcheck`, `--export-json`, `--fast` |
| `scripts/run_collector_continuous.py` | Local runbook | Repeated subprocess-based collection |
| `scripts/run_collector_smoke.py` | Docker image smoke (`NOTICIENCIAS_SMOKE=1`) | Deterministic one-cycle smoke runner; no continuous sleep |
| `scripts/healthcheck.py` | `run_collector.py --healthcheck`, healthcheck runbook | Database, backlog and latest-ingest checks |
| `scripts/migrate.py` | `make migrate` | Alembic wrapper; the only supported schema migration entrypoint |
| `scripts/validate_export.py` | `e2e.yml` | Validates an exported JSON file against the frontend contract |
| `scripts/run_pipeline_e2e.py` | `live-source-drift.yml`, pipeline e2e tests | Deterministic collector-to-frontend scenario and diagnostics |
| `scripts/run_live_source_drift.py` | `live-source-drift.yml` | Live critical-cohort sweep with a differential drift report |
| `scripts/validate_frontend_publication.py` | `publication-smoke.yml` | Backend-driven frontend publication smoke validation |
| `scripts/generate_fixture_post.py` | `publication-smoke.yml` | Writes a production-path v2 AstroPost MDX fixture |
| `scripts/mark_published.py` | Manual reconciliation | Marks collector rows published based on site posts |
| `scripts/ops/pull_webhook_receipts.py` | `make webhooks-pull`, admin stack | Pulls durable frontend callbacks from the hosted serving inbox |
| `scripts/dev/admin_stack.sh` | `make admin` | Starts the serving API and Astro admin together with one Ctrl+C |
| `scripts/smoke_serving_image.sh` | Local runbook | Smoke-checks a built serving image |

## Gates, CI and release

| Script | Invoked by | What it does |
|---|---|---|
| `scripts/check_doc_drift.py` | `make docs-check` | Validates active-doc paths, make targets and declared invariants |
| `scripts/check_doc_review.py` | `make docs-review` | Requires an active-doc review for protected code changes |
| `scripts/check_lock_parity.py` | `make lock-parity-check`, `ci.yml` | Fails when the venv diverges from `requirements.lock` |
| `scripts/check_toolchain.py` | `make toolchain-check`, `ci.yml` | Fails when gate tools drift from `.pre-commit-config.yaml` |
| `scripts/check_migration_revision.py` | Database runbook | Read-only Alembic revision vs. packaged head check |
| `scripts/coverage_ratcheter.sh` | `make type`, coverage CI | Enforces the coverage ratchet for changed files |
| `scripts/export_admin_openapi.py` | `make admin-contracts-generate/-check` | Deterministic admin OpenAPI export and drift check |
| `scripts/generate_api_docs.py` | `make docs-api`, pre-commit | Generates the pdoc API reference (not committed) |
| `scripts/generate_inventory.py` | `make inventory-refresh/-check`, inventory workflows | Generates and compares the repository inventory baseline |
| `scripts/lint_changed.py` | `make lint-changed` | Runs Ruff only on changed Python files |
| `scripts/mutation_score.py` | `make mutation`, `mutation.yml` | Per-module mutation score against the configured floors |
| `scripts/quality_gate.py` | `make quality-gate` | Snapshot-first quality gate (no LLM) |
| `scripts/quality_gate_refresh.py` | `make quality-gate-refresh` | Regenerates quality snapshots with a local LLM |
| `scripts/security_gate.py` | `make security`, `quality.yml` | Interprets pip-audit/Bandit/gitleaks reports and fails on policy violations |
| `scripts/sanitize_gitleaks_report.py` | `quality.yml` | Writes the upload-safe gitleaks report with matched values redacted |
| `scripts/test_suite_audit.py` | `make test-audit`, `make weak-tests-*` | Coverage/weak-test audit and the assertion-free-test ratchet |
| `scripts/validate_context.py` | `make context-validate` | Keeps `context/` module docs in sync with `MODULE_INDEX.md` |
| `scripts/validate_plans_ledger.py` | `make plans-ledger-check` | Fail-closed validation of the `plans/README.md` ledger |
| `scripts/verify_workspace.sh` | Workspace-wide gate in `docs/ci.md` | Runs both repo gates plus schema parity and artifact checks |
| `scripts/sync_lockfiles.py` | `dependency-lock-check.yml`, `manual-lock-sync.yml` | Regenerates/checks hash-pinned lockfiles with pip-tools |
| `scripts/update_changelog.py` | `release.yml` | Updates the changelog during tagged releases |
| `scripts/bump_version.py` | `make bump-version` | Bumps the semantic version in `news_collector/config/VERSION` |

## Evaluation, canaries and reports

These are manually triggered evaluation or reporting tools; none is a PR gate
unless a workflow above says otherwise.

| Script | What it does |
|---|---|
| `scripts/evaluate_enrichment_registry.py` | `make enrichment-eval`: production registry vs. the reviewed corpus (plan 048) |
| `scripts/enrichment_candidate.py`, `scripts/label_enrichment_corpus.py`, `scripts/validate_enrichment_corpus.py` | Build, label and validate the plan 048 enrichment corpus |
| `scripts/editorial_critic_canary.py` | Bounded, sanitized Stage-4 editorial critic canary |
| `scripts/llm_canary.py` | `make llm-canary`: real bounded LLM chain canary |
| `scripts/llm_health_report.py` | `make llm-report`: persisted provider behaviour report |
| `scripts/llm_routing_dataset.py`, `scripts/llm_routing_replay.py` | Dataset selection and offline replay for the LLM routing benchmark |
| `scripts/adversarial_review.py` | `make adversarial-review`: local self-review checklist over a diff |
| `scripts/grounding_backtest.py` | Read-only grounding-rule backtest over published posts |
| `scripts/score_delta.py` | Golden scoring-fixture delta report (see `CONTRIBUTING.md`) |
| `scripts/benchmark_scoring.py`, `scripts/benchmark_bulk_persistence.py`, `scripts/benchmark_metrics.py`, `scripts/benchmark_serving_api.py` | Deterministic performance benchmarks (scoring, persistence, metrics, serving API) |
| `scripts/weekly_quality_report.py`, `scripts/generate_autonomous_report.py`, `scripts/generate_production_report.py` | Weekly/autonomous/production report generators |
| `scripts/lifecycle_reconciliation_report.py`, `scripts/ops/publish_cost_report.py` | Read-only publication lifecycle and cost/SLO reports |

## Operations and maintenance

Manual operator tooling. Inspect `--help` before use; several write to the
configured database.

| Script | What it does |
|---|---|
| `scripts/audit_sources.py`, `scripts/audit_pipeline.py`, `scripts/audit_published_categories.py` | Source health/blacklist audit, unified audit pipeline, published-category audit |
| `scripts/backfill_lifecycle_tables.py` | One-shot backfill of legacy publication blobs into lifecycle tables |
| `scripts/ops/migrate_sources.py` | Normalizes/rewrites `sources.yaml` |
| `scripts/ops/prune_workflow_runs.py` | Deletes terminal `workflow_runs` rows outside the retention window |
| `scripts/ops/purge_short_articles.py` | Deletes articles below the configured length floor |
| `scripts/ops/reconcile_publication_attempts.py` | Reconciles stale `PR_CREATED` publication attempts |
| `scripts/ops/trigger_scoring.py` | Runs one collection/scoring cycle from the CLI |
| `scripts/repair_images.py` | Repairs missing/broken article images |
| `scripts/migrate_metrics_db.py` | Migrates the legacy metrics database |
| `scripts/reset_canary_sources.py` | Resets canary source state |
| `scripts/open_pr.py` | Opens a publication PR from the CLI |
| `scripts/run_secret_scan.py` | Standalone secret-scan helper (tests cover its severity/dir handling) |
| `scripts/profile_pipeline.py` | Profiles a pipeline run (Scalene-friendly) |
| `scripts/verify_imports.py` | Import-graph/circular-import check |
| `scripts/setup/check_env.py` | Checks optional legacy (Streamlit) environment imports |

## One-off / historical

Nothing here is referenced by a gate or supported workflow. Keep for
archaeology; do not extend.

- **`scripts/migrations/20250930_optimize_indexes.py`** — historical raw-DDL
  index migration. It targets the legacy `data/news.db` (or `NEWS_DB_PATH`),
  while the app now uses `data/news_v3.db` (`config.toml`). It is **not** the
  migration path (Alembic, via `make migrate`, is) and must not be run against
  production data.
- `scripts/debug/` — ad-hoc repros for specific scoring/parser/config bugs
  (`debug_google_blog`, `debug_json`, `debug_openai`, `inspect_db`,
  `repro_strip`, `repro_validation`, `verify_cognitive_fix`, `verify_config`,
  `verify_scoring`).
- `scripts/debugging/` — Science-feed connectivity probes; see its local
  `README.md`.
- `scripts/bench_qwen35_json.py`, `scripts/debug_proxy.py`,
  `scripts/reproduce_scoring_bug.py`, `scripts/verify_canary_a_vs_b.py`,
  `scripts/verify_canary_b.py`, `scripts/verify_fix.py`,
  `scripts/verify_prompt.py` — one-off investigations kept for reference.
