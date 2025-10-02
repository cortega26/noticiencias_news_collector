# Noticiencias News Collector — Phase 0 Inventory

## Overview
- **Python version:** 3.12.10 (local interpreter)
- **Top-level layout:** `.bandit`, `.github/`, `config/`, `core/`, `docs/`, `noticiencias/`, `scripts/`, `src/`, `tests/`, plus tooling such as `Makefile`, `pyproject.toml`, `requirements*.txt`, and orchestration entrypoints (`main.py`, `run_collector.py`).
- **Key configuration:** `config.toml`, environment-specific modules under `config/`, and YAML/TOML docs in `docs/`.
- **Data/log folders:** `data/dlq`, `data/logs` (present but empty in snapshot).

## Entry Points & Tooling
- **CLI:** `python run_collector.py --help` — orchestrates full pipeline with options for dry runs, source selection, health checks, and verbosity control.
- **Module:** `main.NewsCollectorSystem` referenced as orchestrator in documentation.
- **Make targets:** bootstrap, lint, lint-fix, typecheck, test, e2e, perf, security, audit-todos, audit-todos-baseline, audit-todos-check, config-gui, config-set, config-validate, config-dump, config-docs, clean, help, bump-version.

## Dependencies Snapshot
- **requirements.txt highlights:** feedparser==6.0.12, requests==2.32.5, beautifulsoup4==4.14.2, lxml==6.0.2, nltk==3.9.2, textblob==0.19.0, python-dateutil==2.9.0.post0, sqlalchemy==2.0.43, python-dotenv==1.1.1, schedule==1.2.2, click==8.3.0, ruamel.yaml==0.18.6, tomli-w==1.0.0, fastapi==0.118.0, pydantic==2.11.9, loguru==0.7.3, pytest==8.4.2.
- **Security extras (pyproject optional):** bandit>=1.7.9, pip-audit>=2.9.0, trufflehog3>=3.0.10.

## Function/Class Index (sample)
| Module | Functions | Classes |
| --- | --- | --- |
| src/collectors/__init__.py | get_available_collector_types, create_collector_by_name | — |
| src/collectors/base_collector.py | create_collector, validate_collector_result | BaseCollector |
| src/collectors/rate_limit_utils.py | _normalize_domain, _candidate_domains, resolve_domain_override, calculate_effective_delay | — |
| src/contracts/collector.py | — | CollectorArticlePayload, CollectorArticleModel |
| src/enrichment/nlp_stack.py | — | NLPResult, LRUCache, ConfigurableNLPStack |
| src/scoring/feature_scorer.py | _get_attr | FeatureWeights, FeatureBasedScorer |
| src/serving/api.py | _decode_cursor, _encode_cursor, _extract_topics, _summarize_why_ranked, _apply_topic_filters, _build_article_payload, create_app | ArticleListParams, ArticleResponse, PaginationResponse, ArticlesEnvelope |
| src/utils/dedupe.py | normalize_article_text, sha256_hex, simhash64, hamming_distance, duplication_confidence, generate_cluster_id | — |
| src/utils/logger.py | get_logger, setup_logging, log_function_calls, log_memory_usage, _log_system_health | NewsCollectorLogger, CollectionSessionLogger |
| src/utils/url_canonicalizer.py | _clean_host, _normalize_path, _filter_query_params, canonicalize_url | — |

*(Full listing in `audit/00_inventory.json` → `function_index_sample`.)*

## Markdown Surface Map
CHANGELOG.md, README.md, CONTRIBUTING.md, docs/*.md (faq, operations, api_examples, collector_runbook, common_output_format, performance_baselines, release_notes, runbook, database_deployment, security, fixtures, placeholder_policy), tests/placeholder_audit/fixtures/doc_page.md, AGENTS.md.

## Open Questions
1. Missing: Confirm actual pytest coverage percentages versus R3 requirement (≥80% overall, ≥90% touched modules).
2. Missing: Validate whether CI enforces bandit/gitleaks/pip-audit baselines or if manual gating is required.

## Verification Checklist (Phase 0)
- Ruff lint (`ruff check src tests scripts`) — pass.
- Mypy type check (`mypy src tests`) — pass (with existing `annotation-unchecked` note).
- Bandit SAST (`bandit -ll -r src scripts`) — **FAIL**: flagged high-severity MD5 usage in `src/utils/dedupe.py:36`; remediation backlog item.
- Gitleaks secret scan — **NOT RUN**: binary unavailable in container (`pip install gitleaks` has no distribution); document as tooling gap.
- Pip-audit (`pip-audit -r requirements.txt`) — **INCOMPLETE**: command hung while building isolated wheels (likely due to heavy packages such as `lxml`); aborted after extended wait.
