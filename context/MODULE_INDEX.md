# Conventions

**Note:** Always consult `context/INVARIANTS.md` for binding architectural invariants before proceeding.

To locate the context file for a module, derive the slug as follows:

- Normalize paths to start at `news_collector/` (strip leading `./` or any repo prefix like `noticiencias_news_collector/`).
- Drop the `news_collector/` prefix (if any)
- Replace `/` with `_`
- Drop the `.py` extension
- The result matches an existing `context/modules/<slug>.md` file.

Module: news_collector/contracts/enrichment.py
Context: context/modules/contracts_enrichment.md
Role: Defines contracts for enrichment pipeline payloads.
Dependencies: None

Module: news_collector/storage/models.py
Context: context/modules/storage_models.md
Role: Defines the ORM data structures used for persisting articles and sources.
Dependencies: None

Module: news_collector/logic/workflows/refinery_engine.py
Context: context/modules/logic_workflows_refinery_engine.md
Role: Orchestrates the refinement pipeline to process articles using an editor agent and write them to a target repository.
Dependencies: news_collector/components/editorial/auditor.py, news_collector/components/editorial/ai_editor.py, news_collector/editorial/policy.py, news_collector/infrastructure/requests_client.py, news_collector/storage/database.py

Module: news_collector/config/settings.py
Context: context/modules/config_settings.md
Role: Provides the project configuration facade backed by Pydantic settings.
Dependencies: None

Module: news_collector/enrichment/pipeline.py
Context: context/modules/enrichment_pipeline.md
Role: Manages the deterministic article enrichment pipeline for extracting multilingual entities, topics, and sentiment.
Dependencies: news_collector/utils/dedupe.py, news_collector/enrichment/nlp_stack.py, news_collector/config/settings.py, news_collector/utils/text_cleaner.py

Module: news_collector/system/bootstrap.py
Context: context/modules/system_bootstrap.md
Role: Encapsulates runtime dependency construction, system startup logic, and initial health checks.
Dependencies: news_collector/collectors/dispatcher.py, news_collector/validation/validator.py, news_collector/config/settings.py

Module: news_collector/storage/database.py
Context: context/modules/storage_database.md
Role: Manages connections, pooling, and CRUD operations for articles and sources.
Dependencies: news_collector/utils/dedupe.py, news_collector/config/settings.py, news_collector/storage/maintenance.py, news_collector/storage/analytics.py, news_collector/storage/models.py, news_collector/utils/pydantic_compat.py

Module: news_collector/utils/logger.py
Context: context/modules/utils_logger.md
Role: Configures the robust and elegant application-wide logging system.
Dependencies: news_collector/config/settings.py

Module: news_collector/scoring/interfaces.py
Context: context/modules/scoring_interfaces.md
Role: Defines protocol abstractions for asynchronous article scorers.
Dependencies: None

Module: news_collector/contracts/adapters.py
Context: context/modules/contracts_adapters.md
Role: Adapts safely between raw ORM or system objects and validated Pydantic contracts.
Dependencies: news_collector/contracts/export.py, news_collector/storage/models.py, news_collector/contracts/validation.py, news_collector/contracts/scoring.py

Module: news_collector/system/pipeline.py
Context: context/modules/system_pipeline.md
Role: Encapsulates the execution orchestration logic of the full news collection cycle.
Dependencies: None

Module: news_collector/monitoring/detectors.py
Context: context/modules/monitoring_detectors.md
Role: Implements anomaly detectors for source health, schema drift, and content shifts.
Dependencies: None

Module: news_collector/contracts/validation.py
Context: context/modules/contracts_validation.md
Role: Defines the payloads for content validation exchanged between system boundaries.
Dependencies: None

Module: news_collector/infrastructure/llm/provider.py
Context: context/modules/infrastructure_llm_provider.md
Role: Provides a unified interface for LLM interactions via an Ollama provider.
Dependencies: news_collector/utils/logger.py

Module: news_collector/observability/enrichment_metrics_store.py
Context: context/modules/observability_enrichment_metrics_store.md
Role: Stores and aggregates metrics from the enrichment pipeline strategies.
Dependencies: news_collector/infrastructure/run_context.py

Module: news_collector/collectors/base_collector.py
Context: context/modules/collectors_base_collector.md
Role: Defines the common interface that all data collectors must implement.
Dependencies: news_collector/collectors/headless_collector.py, news_collector/config/settings.py, news_collector/utils/text_cleaner.py, news_collector/storage/database.py, news_collector/utils/logger.py, news_collector/collectors/html_collector.py, news_collector/diagnostics.py, news_collector/collectors/rss_collector.py, news_collector/collectors/rate_limit_utils.py

Module: news_collector/components/editorial/ai_editor.py
Context: context/modules/components_editorial_ai_editor.md
Role: Modifies and refines article content using LLM integrations.
Dependencies: news_collector/config/settings.py, news_collector/contracts/frontend_schema.py, news_collector/utils/logger.py, news_collector/taxonomy/normalizer.py, news_collector/infrastructure/llm/provider.py

Module: news_collector/enrichment/router.py
Context: context/modules/enrichment_router.md
Role: Decides and executes the appropriate enrichment strategy for a given article.
Dependencies: news_collector/observability/enrichment_metrics_store.py, news_collector/enrichment/strategy_optimizer.py, news_collector/enrichment/http_enricher.py, news_collector/enrichment/scholarly.py, news_collector/enrichment/headless_enricher.py, news_collector/enrichment/strategy_lock_manager.py, news_collector/infrastructure/run_context.py

Module: news_collector/scoring/basic_scorer.py
Context: context/modules/scoring_basic_scorer.md
Role: Evaluates articles across dimensions like credibility, recency, and quality to compute a final score.
Dependencies: news_collector/storage/models.py, news_collector/config/settings.py, news_collector/scoring/interfaces.py

Module: news_collector/storage/analytics.py
Context: context/modules/storage_analytics.md
Role: Provides analytics helpers for database reporting.
Dependencies: news_collector/storage/models.py

Module: news_collector/storage/maintenance.py
Context: context/modules/storage_maintenance.md
Role: Provides maintenance helpers for database cleanup and health checks.
Dependencies: news_collector/storage/models.py

Module: news_collector/contracts/common.py
Context: context/modules/contracts_common.md
Role: Provides common shared contract definitions.
Dependencies: news_collector/contracts/enrichment.py

Module: news_collector/utils/text_cleaner.py
Context: context/modules/utils_text_cleaner.md
Role: Provides utilities for cleaning and sanitizing extracted raw text.
Dependencies: None

Module: news_collector/logic/parsers/rss_parser.py
Context: context/modules/logic_parsers_rss_parser.md
Role: Parses RSS feeds and extracts standardized article metadata.
Dependencies: news_collector/utils/datetime_utils.py, news_collector/utils/text_cleaner.py, news_collector/utils/url_canonicalizer.py

Module: news_collector/contracts/export.py
Context: context/modules/contracts_export.md
Role: Defines data contracts used for system export operations.
Dependencies: None
