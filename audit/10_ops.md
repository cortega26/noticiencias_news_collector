# Phase 10 — Observability & Reliability Audit

## Overview
- **Objective:** Improve diagnostics for collector runs and ensure ops teams can triage healthcheck signals quickly.
- **Scope:** Structured logging for collectors, healthcheck CLI semantics, documentation (README + runbooks), and CI guardrails.

## Changes Delivered
1. **Structured logging context propagation**
   - Bound `trace_id`, `session_id`, and per-article metadata inside `BaseCollector` and RSS collectors (sync/async).
   - Added `_emit_log` helper with consistent event families (e.g., `collector.article.saved`).
   - Ensured downstream save paths surface DLQ context and robots.txt decisions.
2. **Healthcheck behavior + docs**
   - `scripts/healthcheck.py` now treats "no recent ingest" as a warning (non-failing) while preserving stale-ingest failures.
   - Authored `docs/runbooks/healthcheck.md` with config table, troubleshooting, and log mapping; linked from README and collector runbook.
3. **CI & runbooks**
   - Added GitHub Actions job executing `python run_collector.py --healthcheck` with strict thresholds.
   - Captured remediation guidance inside existing collector runbook.

## Verification
| Check | Command | Result |
| --- | --- | --- |
| Unit & integration tests | `make test` | ✅ `145 passed` |
| Targeted pipeline tests | `.venv/bin/pytest tests/test_collector_pipeline_e2e.py tests/perf/test_pipeline_perf.py tests/test_main_initialization.py` | ✅ |
| Security | `pip-audit`, `bandit`, `trufflehog` via Make targets | ✅ No HIGH findings |
| Healthcheck proof | `.venv/bin/python run_collector.py --healthcheck --healthcheck-max-pending 0 --healthcheck-max-ingest-minutes 60` | ⚠️ Warns on empty ingest as expected |

## Outstanding Risks / Follow-ups
- Coverage for new error branches (robots blocking, DLQ failures) remains partial; consider targeted integration tests.
- Async RSS collector logging mirrors sync path; add async-specific assertions when harness available.
- Overall coverage remains ~72% because legacy scoring modules lack tests; recommend dedicated effort to raise ≥80%.

