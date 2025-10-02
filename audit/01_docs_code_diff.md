# 01 — Docs ↔ Code Consistency Gap Report

## Scope & Method
- Scanned `README.md` and `docs/*.md` for CLI commands, configuration references, and operational runbooks.
- Queried the runtime CLI entry points (`python run_collector.py --help`, `python -m noticiencias.config_manager --help`) to confirm published flags.
- Inspected configuration sources (`config.toml`, `config/settings.py`, `config/sources.py`) to verify documented paths and keys.
- Executed documented scripts where possible to validate invocation instructions.

## Findings
| ID | Documentation | Documented Claim | Reality | Impact | Proposed Fix |
| --- | --- | --- | --- | --- | --- |
| D1 | `docs/faq.md` (429 section) | Mentions tuning `config/sources.yaml` / `config/rate_limits.yaml`. | Project ships Python modules (`config/sources.py`) and TOML config (`config.toml`), no YAML files exist. | Operators chasing YAML files cannot remediate rate-limit incidents. | Update references to `config/sources.py` and `[rate_limiting]` in `config.toml`. |
| D2 | `docs/faq.md` (429 section) | Advises running `python scripts/rate_limit_probe.py --source <id>`. | Script `scripts/rate_limit_probe.py` is absent; available utility is `scripts/load_test.py`. | Troubleshooting playbook cannot be executed as written. | Swap to `python -m scripts.load_test --num-sources 1 --concurrency 1` guidance. |
| D3 | `docs/faq.md` (ModuleNotFoundError section) | Points to `config/enrichment.yaml` for model paths. | Enrichment configuration lives under `[enrichment.models]` in `config.toml`. | Engineers will edit nonexistent YAML and miss the real source of truth. | Reference `config.toml` enrichment section instead. |
| D4 | `README.md` (scripts table) | Suggests `python scripts/healthcheck.py --max-ingest-minutes 30`. | Direct execution fails (`ModuleNotFoundError: No module named 'src'`) because Python omits the project root from `sys.path`. | Runbook automation and manual invocations fail unless engineers debug path issues. | Recommend `python -m scripts.healthcheck --max-ingest-minutes 30`, which succeeds. |

## Command Verification
- `python run_collector.py --help` ✅
- `python -m noticiencias.config_manager --help` ✅ (emits runpy warning; functionality OK)
- `python scripts/healthcheck.py --help` ❌ (`ModuleNotFoundError: No module named 'src'`)
- `python -m scripts.healthcheck --help` ✅

## Next Steps
Apply the documentation edits captured in `audit/01_docs_fixes.patch` and ensure future CLI documentation uses module invocations for scripts that rely on project-relative imports.
