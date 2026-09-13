# Conventions

**Status:** Derived, selected navigation index. Engineering authority lives in
`docs/SOURCE_OF_TRUTH.md` and `docs/AGENTS.md`; `context/INVARIANTS.md` is a summary.
For signatures, callers and side effects inspect source or CodeGraph, not this index.

To locate the context file for a module, derive the slug as follows:

- Normalize paths to start at `news_collector/` (strip leading `./` or any repo prefix like `noticiencias_news_collector/`).
- Drop the `news_collector/` prefix (if any)
- Replace `/` with `_`
- Drop the `.py` extension
- If the module is indexed, the result matches its context filename. Unlisted
  modules still exist and must be inspected when relevant.

Module: news_collector/contracts/enrichment.py
Context: context/modules/contracts_enrichment.md
Role: Defines contracts for enrichment pipeline payloads.

Module: news_collector/storage/models.py
Context: context/modules/storage_models.md
Role: Defines the ORM data structures used for persisting articles and sources.

Module: news_collector/logic/workflows/refinery_engine.py
Context: context/modules/logic_workflows_refinery_engine.md
Role: Orchestrates the refinement pipeline to process articles using an editor agent and write them to a target repository.

Module: news_collector/config/settings.py
Context: context/modules/config_settings.md
Role: Provides the project configuration facade backed by Pydantic settings.

Module: news_collector/enrichment/pipeline.py
Context: context/modules/enrichment_pipeline.md
Role: Manages the deterministic article enrichment pipeline for extracting multilingual entities, topics, and sentiment.

Module: news_collector/system/bootstrap.py
Context: context/modules/system_bootstrap.md
Role: Encapsulates runtime dependency construction, system startup logic, and initial health checks.

Module: news_collector/storage/database.py
Context: context/modules/storage_database.md
Role: Manages connections, pooling, and CRUD operations for articles and sources.

Module: news_collector/utils/logger.py
Context: context/modules/utils_logger.md
Role: Configures application logging and contextual logging helpers.

Module: news_collector/scoring/interfaces.py
Context: context/modules/scoring_interfaces.md
Role: Defines protocol abstractions for asynchronous article scorers.

Module: news_collector/contracts/adapters.py
Context: context/modules/contracts_adapters.md
Role: Adapts safely between raw ORM or system objects and validated Pydantic contracts.

Module: news_collector/system/pipeline.py
Context: context/modules/system_pipeline.md
Role: Encapsulates the execution orchestration logic of the full news collection cycle.

Module: news_collector/monitoring/detectors.py
Context: context/modules/monitoring_detectors.md
Role: Implements anomaly detectors for source health, schema drift, and content shifts.

Module: news_collector/contracts/validation.py
Context: context/modules/contracts_validation.md
Role: Defines the payloads for content validation exchanged between system boundaries.

Module: news_collector/infrastructure/llm/provider.py
Context: context/modules/infrastructure_llm_provider.md
Role: Provides a unified interface for LLM interactions via an Ollama provider.

Module: news_collector/observability/enrichment_metrics_store.py
Context: context/modules/observability_enrichment_metrics_store.md
Role: Stores and aggregates metrics from the enrichment pipeline strategies.

Module: news_collector/collectors/base_collector.py
Context: context/modules/collectors_base_collector.md
Role: Defines the common interface that all data collectors must implement.

Module: news_collector/components/editorial/ai_editor.py
Context: context/modules/components_editorial_ai_editor.md
Role: Modifies and refines article content using LLM integrations.

Module: news_collector/enrichment/router.py
Context: context/modules/enrichment_router.md
Role: Decides and executes the appropriate enrichment strategy for a given article.

Module: news_collector/scoring/basic_scorer.py
Context: context/modules/scoring_basic_scorer.md
Role: Evaluates articles across dimensions like credibility, recency, and quality to compute a final score.

Module: news_collector/storage/analytics.py
Context: context/modules/storage_analytics.md
Role: Provides analytics helpers for database reporting.

Module: news_collector/storage/maintenance.py
Context: context/modules/storage_maintenance.md
Role: Provides maintenance helpers for database cleanup and health checks.

Module: news_collector/contracts/common.py
Context: context/modules/contracts_common.md
Role: Provides common shared contract definitions.

Module: news_collector/utils/text_cleaner.py
Context: context/modules/utils_text_cleaner.md
Role: Provides utilities for cleaning and sanitizing extracted raw text.

Module: news_collector/logic/parsers/rss_parser.py
Context: context/modules/logic_parsers_rss_parser.md
Role: Parses RSS feeds and extracts standardized article metadata.

Module: news_collector/contracts/export.py
Context: context/modules/contracts_export.md
Role: Defines data contracts used for system export operations.

Module: news_collector/logic/workflows/collection_run_workflow.py
Context: context/modules/logic_workflows_collection_run_workflow.md
Role: Owns durable collection run lifecycle and lease recovery.

Module: news_collector/logic/workflows/publication_run_workflow.py
Context: context/modules/logic_workflows_publication_run_workflow.md
Role: Owns durable publication run lifecycle and lease recovery.
