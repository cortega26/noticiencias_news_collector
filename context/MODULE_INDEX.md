Module: news_collector/contracts/enrichment.py
Role: Defines contracts for enrichment pipeline payloads.
Dependencies: None
Used by: common

Module: news_collector/storage/models.py
Role: Defines the ORM data structures used for persisting articles and sources.
Dependencies: None
Used by: heuristic_scorer, basic_scorer, cognitive_scorer, database, analytics, maintenance, adapters, api

Module: news_collector/logic/workflows/refinery_engine.py
Role: Orchestrates the refinement pipeline to process articles using an editor agent and write them to a target repository.
Dependencies: auditor, ai_editor, policy, requests_client, database
Used by: None

Module: news_collector/config/settings.py
Role: Provides the project configuration facade backed by Pydantic settings.
Dependencies: None
Used by: logger, basic_scorer, database, collector, ai_editor, rss_collector, rate_limit_utils, base_collector, html_collector, pipeline, http_client, requests_client, bootstrap, activity_monitor

Module: news_collector/enrichment/pipeline.py
Role: Manages the deterministic article enrichment pipeline for extracting multilingual entities, topics, and sentiment.
Dependencies: dedupe, nlp_stack, settings, text_cleaner
Used by: None

Module: news_collector/system/bootstrap.py
Role: Encapsulates runtime dependency construction, system startup logic, and initial health checks.
Dependencies: dispatcher, validator, settings
Used by: None

Module: news_collector/storage/database.py
Role: Manages connections, pooling, and CRUD operations for articles and sources.
Dependencies: dedupe, settings, maintenance, analytics, models, pydantic_compat
Used by: refinery_engine, base_collector, api

Module: news_collector/utils/logger.py
Role: Configures the robust and elegant application-wide logging system.
Dependencies: settings
Used by: policy, ai_editor, auditor, github_publisher, rss_collector, base_collector, html_collector, provider

Module: news_collector/scoring/interfaces.py
Role: Defines protocol abstractions for asynchronous article scorers.
Dependencies: None
Used by: feature_scorer, basic_scorer

Module: news_collector/contracts/adapters.py
Role: Adapts safely between raw ORM or system objects and validated Pydantic contracts.
Dependencies: export, models, validation, scoring
Used by: None

Module: news_collector/system/pipeline.py
Role: Encapsulates the execution orchestration logic of the full news collection cycle.
Dependencies: None
Used by: None

Module: news_collector/monitoring/detectors.py
Role: Implements anomaly detectors for source health, schema drift, and content shifts.
Dependencies: common
Used by: reporting, io, canary

Module: news_collector/contracts/validation.py
Role: Defines the payloads for content validation exchanged between system boundaries.
Dependencies: None
Used by: adapters

Module: news_collector/infrastructure/llm/provider.py
Role: Provides a unified interface for LLM interactions via an Ollama provider.
Dependencies: logger
Used by: pre_scorer, cognitive_scorer, classifier, council, ai_editor, auditor

Module: news_collector/observability/enrichment_metrics_store.py
Role: Stores and aggregates metrics from the enrichment pipeline strategies.
Dependencies: run_context
Used by: strategy_lock_manager, strategy_optimizer, router, proxy_manager

Module: news_collector/collectors/base_collector.py
Role: Defines the common interface that all data collectors must implement.
Dependencies: headless_collector, settings, text_cleaner, database, logger, html_collector, diagnostics, rss_collector, rate_limit_utils
Used by: rss_collector, headless_collector, dispatcher, html_collector

Module: news_collector/components/editorial/ai_editor.py
Role: Modifies and refines article content using LLM integrations.
Dependencies: settings, frontend_schema, logger, normalizer, provider
Used by: refinery_engine

Module: news_collector/enrichment/router.py
Role: Decides and executes the appropriate enrichment strategy for a given article.
Dependencies: enrichment_metrics_store, strategy_optimizer, http_enricher, scholarly, headless_enricher, strategy_lock_manager, run_context
Used by: rss_collector

Module: news_collector/scoring/basic_scorer.py
Role: Evaluates articles across dimensions like credibility, recency, and quality to compute a final score.
Dependencies: models, settings, interfaces
Used by: cognitive_scorer

Module: news_collector/storage/analytics.py
Role: Provides analytics helpers for database reporting.
Dependencies: models
Used by: database

Module: news_collector/storage/maintenance.py
Role: Provides maintenance helpers for database cleanup and health checks.
Dependencies: models
Used by: database

Module: news_collector/contracts/common.py
Role: Provides common shared contract definitions.
Dependencies: enrichment
Used by: collector

Module: news_collector/utils/text_cleaner.py
Role: Provides utilities for cleaning and sanitizing extracted raw text.
Dependencies: None
Used by: dedupe, rss_parser, base_collector, nlp_stack, pipeline

Module: news_collector/logic/parsers/rss_parser.py
Role: Parses RSS feeds and extracts standardized article metadata.
Dependencies: datetime_utils, text_cleaner, url_canonicalizer
Used by: rss_collector

Module: news_collector/contracts/export.py
Role: Defines data contracts used for system export operations.
Dependencies: None
Used by: adapters
