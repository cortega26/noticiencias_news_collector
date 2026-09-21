# Test-suite audit (baseline 2026-09-20)

Produced with `make test-audit` (`scripts/test_suite_audit.py`, logic in the
same script). Numbers below are from the first run and are the
backlog for the follow-up PRs (see `todo-test-suite-audit.md`).

## Coverage, measured honestly
The pytest default (`--cov=news_collector --cov=apps`) hid two packages. Full picture:

| scope | lines | branches |
|---|---:|---:|
| `news_collector` + `apps` (what CI gates today) | 90.9 % | 81.1 % |
| + `noticiencias` (config schema/manager, cross-repo contract) | 88.3 % | 78.2 % |
| `scripts/` (87 files; many one-off tools) | 22.9 % | 19.9 % |

`.coverage-baseline` (85.20 % lines / 73.43 % branch, August) is stale: the real floor is ~9 points higher.

## Critical gaps (production code, <85 %, by missing lines)
| file | lines % | missing |
|---|---:|---:|
| apps/refinery/admin_panel.py | 4.3 | 1304 |
| noticiencias/gui_config.py | 0.0 | 383 |
| noticiencias/config_manager.py | 53.9 | 238 |
| news_collector/logic/workflows/pipeline_e2e.py | 42.7 | 223 |
| news_collector/utils/logger.py | 51.6 | 89 |
| news_collector/scoring/basic_scorer.py | 76.0 | 87 |
| apps/refinery/published_content.py | 77.5 | 83 |
| news_collector/collectors/reddit_collector.py | 25.2 | 80 |
| news_collector/enrichment/scrapling_enricher.py | 22.0 | 78 |
| news_collector/perf/load_replay.py | 51.7 | 71 |
| news_collector/components/editorial/auditor.py | 74.9 | 69 |
| news_collector/collectors/headless_collector.py | 60.5 | 58 |
| news_collector/enrichment/nlp_stack.py | 79.4 | 52 |
| news_collector/collectors/html_collector.py | 79.7 | 42 |

Notes: `noticiencias/gui_config.py` (383 lines, 0 %) is the legacy Streamlit config GUI (candidate
for removal); `noticiencias/config_manager.py` is a real gap (loading/validation of the
sealed config contract). Zero-coverage scripts include CI-relevant ones (`sync_lockfiles`,
`bump_version`, `validate_plans_ledger`, `quality_gate_refresh`, `update_changelog`).

## Tests that do not point at repo code
- `tests/spikes/` (32 tests): a self-contained prototype (plan 049), imports nothing from the repo.
- `tests/legacy/` (2), `tests/verify_async.py` (imports the non-existent `news_collector.collectors.async_rss_collector`), `tests/verify_phase1.py`, `tests/debug_*.py` (not tests).
- ~186 tests execute no *measured* line; most are legitimate (CLI/subprocess tests of scripts, opt-in cross-repo/network tests, import-time contract checks) — the report is a heuristic to review, not a delete list.

## Weak tests (static)
- 41 test functions without any assertion (e.g. `test_async_scoring`, `test_pipeline_flow_simplified`, `test_requests_client_integration`): some are legitimate "must not raise", others empty.
- 12 files with >=6 mock operations per test (`test_main_manual_url`: 60 mocks / 4 tests) — risk of asserting on the fakes.

## Speed / stability
Full run ~110-140 s; the slowest tests are real sleeps in backoff tests (5.0 s, 3.5 s, 2.0 s) — candidates
to inject a fake clock. `pytest-randomly` shuffles every CI run; the suite passed with the clock +120 days
in #288 (only the expiring pip-audit allowlist tests fail, by design). A multi-seed stability sweep is still to do (Phase 0 follow-up).

## Mutation testing baseline (2026-09-20, `make mutation`, mutmut 3)
Line coverage says a line ran; mutation score says a test would *notice* the line changing.
First run over five critical pure modules (1 204 mutants, ~2 min):

| module | detected | survived | score |
|---|---:|---:|---:|
| `collectors/admission.py` | 102 | 0 | 100 % (was 82 %: 18 survivors) |
| `editorial/grounding.py` | 446 | 103 | 81 % |
| `infrastructure/llm/failure_kinds.py` | 43 | 10 | 81 % |
| `observability/llm_run_report.py` | 180 | 88 | 67 % |
| `utils/url_canonicalizer.py` | 141 | 91 | 61 % |

`admission.py` had 100 % line coverage yet 18 survivors: the built-in defaults (30 days / 10 / 1000), the
exact age boundary, the window floor and the `details` payload were pinned by no test; 9 new tests
(`test_admission_defaults_and_details.py`) kill them all. Floors per module live in
`[tool.mutation.floors]` and are enforced by `scripts/mutation_score.py --check` in the weekly
`mutation.yml`; raise them as survivors are killed. One test
(`test_emit_logs_a_degraded_event_and_can_be_disabled`) reads `fn.__globals__`, which breaks under mutmut's
trampoline: deselected in the mutation run and flagged as a test smell to rewrite.
