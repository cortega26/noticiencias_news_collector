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
3. Anything in [One-off / historical](#one-off--historical) is not called by a
   gate or a supported workflow. Some still work as manual tools; read the
   header before running, and never point one at production data.
4. Add new scripts to this index in the same PR that adds them.

`scripts/audit.coveragerc` is the coverage configuration used by
`make test-audit`; `scripts/__init__.py` makes `scripts` importable for tests.
Neither is an entrypoint.

## Collector, pipeline and serving

| Script | Invoked by | What it does |
|---|---|---|
| `scripts/run_collector.py` | `make run-local`, `ci.yml` e2e, `daily_collector.yml` | Primary collector CLI: `--dry-run`, `--sources`, `--healthcheck`, `--export-json`, `--fast` |
| `scripts/run_collector_continuous.py` | Local runbook | Repeated subprocess-based collection; uses the smoke runner when `NOTICIENCIAS_SMOKE` is set |
| `scripts/run_collector_smoke.py` | `run_collector_continuous.py`, smoke tests | Deterministic one-cycle replay smoke runner |
| `scripts/healthcheck.py` | `run_collector.py --healthcheck`, healthcheck runbook | Database, backlog and latest-ingest checks |
| `scripts/migrate.py` | `make migrate` | Alembic wrapper; the only supported schema migration entrypoint |
| `scripts/validate_export.py` | `e2e.yml` | Validates an exported JSON file against the frontend contract |
| `scripts/run_pipeline_e2e.py` | `live-source-drift.yml`, pipeline e2e tests | Deterministic collector-to-frontend scenario and diagnostics |
| `scripts/run_live_source_drift.py` | `live-source-drift.yml` | Live critical-cohort sweep with a differential drift report |
| `scripts/validate_frontend_publication.py` | `publication-smoke.yml` | Backend-driven frontend publication smoke validation |
| `scripts/generate_fixture_post.py` | `publication-smoke.yml` | Writes a production-path v2 AstroPost MDX fixture |
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
| `scripts/ops/reconcile_publication_attempts.py` | Publication contract runbook | Reconciles stale `PR_CREATED` publication attempts |

## Evaluation, canaries and reports

These are manual tooling named by the active docs or a Makefile target.

| Script | What it does |
|---|---|
| `scripts/evaluate_enrichment_registry.py` | `make enrichment-eval`: production registry vs. the reviewed corpus (plan 048) |
| `scripts/editorial_critic_canary.py` | Bounded, sanitized Stage-4 editorial critic canary |
| `scripts/llm_canary.py` | `make llm-canary`: real bounded LLM chain canary |
| `scripts/llm_health_report.py` | `make llm-report`: persisted provider behaviour report |
| `scripts/adversarial_review.py` | `make adversarial-review`: local self-review checklist over a diff |
| `scripts/grounding_backtest.py` | Read-only grounding-rule backtest over published posts |
| `scripts/benchmark_serving_api.py` | Deterministic serving API benchmark (see `docs/performance_baselines.md`) |
| `scripts/score_delta.py` | Golden scoring-fixture delta report (see `CONTRIBUTING.md`) |

## One-off / historical

Nothing here is referenced by a Makefile target, workflow or active doc. Keep
for archaeology; do not extend.

- **`scripts/migrations/20250930_optimize_indexes.py`** — historical raw-DDL
  index migration. It targets the legacy `data/news.db` (or `NEWS_DB_PATH`),
  while the app now uses `data/news_v3.db` (`config.toml`). It is **not** the
  migration path (Alembic, via `make migrate`, is) and must not be run against
  production data.
- **Debug probes** — `scripts/debug/` (nine ad-hoc repros for scoring, parser,
  config and database issues) and `scripts/debugging/` (Science-feed
  connectivity probes; see its local `README.md`).
- **Source and data audits** — `scripts/audit_sources.py`,
  `scripts/audit_pipeline.py`, `scripts/audit_published_categories.py`,
  `scripts/ops/migrate_sources.py`.
- **Database/data maintenance** — `scripts/backfill_lifecycle_tables.py`,
  `scripts/migrate_metrics_db.py`, `scripts/ops/prune_workflow_runs.py`,
  `scripts/ops/purge_short_articles.py`, `scripts/ops/trigger_scoring.py`,
  `scripts/repair_images.py`, `scripts/reset_canary_sources.py`.
- **Report generators** — `scripts/weekly_quality_report.py`,
  `scripts/generate_autonomous_report.py`,
  `scripts/generate_production_report.py`,
  `scripts/lifecycle_reconciliation_report.py`,
  `scripts/ops/publish_cost_report.py`.
- **Benchmarks** — `scripts/benchmark_scoring.py`,
  `scripts/benchmark_bulk_persistence.py`, `scripts/benchmark_metrics.py`.
- **Evaluation candidates** — `scripts/enrichment_candidate.py`,
  `scripts/label_enrichment_corpus.py`,
  `scripts/validate_enrichment_corpus.py`, `scripts/llm_routing_dataset.py`,
  `scripts/llm_routing_replay.py`.
- **One-off helpers** — `scripts/mark_published.py`, `scripts/open_pr.py`,
  `scripts/run_secret_scan.py`, `scripts/profile_pipeline.py`,
  `scripts/setup/check_env.py`, `scripts/bench_qwen35_json.py`,
  `scripts/debug_proxy.py`, `scripts/reproduce_scoring_bug.py`,
  `scripts/verify_canary_a_vs_b.py`, `scripts/verify_canary_b.py`,
  `scripts/verify_fix.py`, `scripts/verify_imports.py`,
  `scripts/verify_prompt.py`.
