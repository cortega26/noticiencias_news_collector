| Field | Type | Default | Description | Constraints | Example |
| --- | --- | --- | --- | --- | --- |
| app | AppSettings |  |  |  |  |
| app.environment | str | "development" | Normalized deployment environment name. |  | production |
| app.debug | bool | false | When true, enables verbose logging and relaxed guards. |  |  |
| app.timezone | str | "UTC" | Default timezone for user-facing timestamps. |  | America/Santiago |
| paths | PathsConfig |  |  |  |  |
| paths.data_dir | Path | data | Root directory for persistent runtime artefacts. |  | /var/lib/noticiencias |
| paths.logs_dir | Path | logs | Directory where operational logs are written. |  | /var/log/noticiencias |
| paths.dlq_dir | Path | dlq | Storage directory for dead-letter queue payloads. |  |  |
| database | DatabaseConfig |  |  |  |  |
| database.driver | str | "sqlite" | Database backend driver to use. |  | postgresql |
| database.path | Optional | data/news.db | Filesystem path for SQLite database files. |  |  |
| database.host | Optional |  | Hostname for the SQL server when using a network backend. |  | db.internal |
| database.port | Optional |  | TCP port for the SQL server backend. |  | 5432 |
| database.name | str | "noticiencias" | Database name or schema. |  |  |
| database.user | Optional |  | Database username for authenticated connections. |  |  |
| database.password | Optional |  | Database password; treated as secret. |  |  |
| database.sslmode | Optional |  | libpq-compatible SSL mode string for PostgreSQL. |  |  |
| database.connect_timeout | int | 10 | Seconds to wait when establishing a connection. |  |  |
| database.statement_timeout | int | 30000 | Maximum execution time for SQL statements (ms). |  |  |
| database.pool_size | int | 10 | Number of persistent connections per worker. |  |  |
| database.max_overflow | int | 5 | How many extra connections can be opened temporarily. |  |  |
| database.pool_timeout | int | 30 | Seconds to wait when the pool is exhausted before failing. |  |  |
| database.pool_recycle | int | 1800 | Seconds after which pooled connections are recycled. |  |  |
| collection | CollectionConfig |  |  |  |  |
| collection.collection_interval_hours | int | 6 | Interval between collector runs in hours. |  |  |
| collection.request_timeout_seconds | int | 30 | HTTP request timeout used by collectors. |  |  |
| collection.async_enabled | bool | false | Enable asyncio-based fetchers when available. |  |  |
| collection.max_concurrent_requests | int | 8 | Concurrency limit for async collectors. |  |  |
| collection.max_articles_per_source | int | 50 | Cap on articles per source per run. |  |  |
| collection.recent_days_threshold | int | 7 | Number of trailing days considered 'recent'. |  |  |
| collection.user_agent | str | "NoticienciasBot/1.0 (+https://noticiencias.com)" | HTTP User-Agent header sent to providers. |  |  |
| collection.canonicalization_cache_size | int | 2048 | LRU cache size for canonical URLs (0 disables caching). |  |  |
| rate_limiting | RateLimitingConfig |  |  |  |  |
| rate_limiting.delay_between_requests_seconds | float | 1.0 | Base delay enforced between requests to the same source. |  |  |
| rate_limiting.domain_default_delay_seconds | float | 1.0 | Fallback delay applied when a domain has no override. |  |  |
| rate_limiting.domain_overrides | Dict | {"export.arxiv.org": 20.0, "arxiv.org": 20.0, "www.reddit.com": 30.0, "reddit.com": 30.0} | Per-domain throttle overrides in seconds. |  |  |
| rate_limiting.max_retries | int | 3 | Maximum number of retry attempts per request. |  |  |
| rate_limiting.retry_delay_seconds | float | 1.0 | Initial delay between retries, subject to backoff. |  |  |
| rate_limiting.backoff_base | float | 0.5 | Base factor for exponential backoff. |  |  |
| rate_limiting.backoff_max | float | 10.0 | Maximum jitter-free delay enforced by backoff. |  |  |
| rate_limiting.jitter_max | float | 0.3 | Maximum random jitter added to delays. |  |  |
| robots | RobotsConfig |  |  |  |  |
| robots.respect_robots | bool | true | Honor robots.txt directives when collecting. |  |  |
| robots.cache_ttl_seconds | int | 3600 | Seconds to cache robots.txt fetch results. |  |  |
| dedup | DedupConfig |  |  |  |  |
| dedup.simhash_threshold | int | 10 | Maximum allowed SimHash distance for duplicates. |  |  |
| dedup.simhash_candidate_window | int | 500 | Window size for near-duplicate candidate search. |  |  |
| scoring | ScoringConfig |  |  |  |  |
| scoring.weights | WeightsConfig |  |  |  |  |
| scoring.weights.source_credibility | float | 0.25 | Weight applied to source trustworthiness scoring feature. |  |  |
| scoring.weights.recency | float | 0.2 | Weight for publication recency component. |  |  |
| scoring.weights.content_quality | float | 0.25 | Weight for content quality heuristics. |  |  |
| scoring.weights.engagement_potential | float | 0.3 | Weight for predicted audience engagement. |  |  |
| scoring.feature_weights | FeatureWeightsConfig |  |  |  |  |
| scoring.feature_weights.source_credibility | float | 0.3 |  |  |  |
| scoring.feature_weights.freshness | float | 0.25 |  |  |  |
| scoring.feature_weights.content_quality | float | 0.25 |  |  |  |
| scoring.feature_weights.engagement | float | 0.2 |  |  |  |
| scoring.daily_top_count | int | 10 | Number of articles promoted per day. |  |  |
| scoring.minimum_score | float | 0.3 | Minimum score required for surfacing an article. |  |  |
| scoring.mode | str | "advanced" | Active scoring pipeline variant (basic|advanced). |  | basic |
| scoring.workers | int | 4 |  |  |  |
| scoring.freshness | FreshnessConfig |  |  |  |  |
| scoring.freshness.half_life_hours | float | 18.0 |  |  |  |
| scoring.freshness.max_decay_hours | float | 168.0 |  |  |  |
| scoring.diversity_penalty | DiversityPenaltyConfig |  |  |  |  |
| scoring.diversity_penalty.weight | float | 0.15 |  |  |  |
| scoring.diversity_penalty.max_penalty | float | 0.3 |  |  |  |
| scoring.content_quality_heuristics | ContentQualityHeuristics |  |  |  |  |
| scoring.content_quality_heuristics.title_length_divisor | float | 120.0 |  |  |  |
| scoring.content_quality_heuristics.summary_length_divisor | float | 400.0 |  |  |  |
| scoring.content_quality_heuristics.entity_target_count | float | 5.0 |  |  |  |
| scoring.content_quality_heuristics.weights | ContentQualityWeights |  |  |  |  |
| scoring.content_quality_heuristics.weights.title | float | 0.4 |  |  |  |
| scoring.content_quality_heuristics.weights.summary | float | 0.4 |  |  |  |
| scoring.content_quality_heuristics.weights.entity | float | 0.2 |  |  |  |
| scoring.engagement_heuristics | EngagementHeuristics |  |  |  |  |
| scoring.engagement_heuristics.sentiment_scores | SentimentScores |  |  |  |  |
| scoring.engagement_heuristics.sentiment_scores.positive | float | 0.7 |  |  |  |
| scoring.engagement_heuristics.sentiment_scores.negative | float | 0.6 |  |  |  |
| scoring.engagement_heuristics.sentiment_scores.neutral | float | 0.5 |  |  |  |
| scoring.engagement_heuristics.fallback_sentiment | float | 0.5 |  |  |  |
| scoring.engagement_heuristics.word_count_divisor | float | 800.0 |  |  |  |
| scoring.engagement_heuristics.external_weight | float | 0.6 |  |  |  |
| scoring.engagement_heuristics.length_weight | float | 0.4 |  |  |  |
| scoring.reranker_seed | int | 1337 |  |  |  |
| scoring.source_cap_percentage | float | 0.5 |  |  |  |
| scoring.topic_cap_percentage | float | 0.6 |  |  |  |
| text_processing | TextProcessingConfig |  |  |  |  |
| text_processing.supported_languages | List | ["en", "es", "pt", "fr"] | Languages supported by NLP routines. |  |  |
| text_processing.min_content_length | int | 100 | Minimum number of characters required for an article. |  |  |
| text_processing.boost_keywords | List | ["breakthrough", "discovery", "research", "study", "clinical trial", "peer-reviewed", "published", "journal", "university", "scientists", "artificial intelligence", "machine learning", "climate change", "medical", "technology", "innovation", "Nobel", "FDA approved"] | Keywords boosting article relevance. |  |  |
| text_processing.penalty_keywords | List | ["shocking", "you won't believe", "doctors hate", "miracle cure", "secret", "conspiracy", "hoax", "fake news"] | Keywords penalizing credibility (clickbait). |  |  |
| enrichment | EnrichmentConfig |  |  |  |  |
| enrichment.default_model | str | "pattern_v1" |  |  |  |
| enrichment.analysis_cache_size | int | 512 |  |  |  |
| enrichment.result_cache_size | int | 256 |  |  |  |
| enrichment.models | Dict | {'pattern_v1': ModelConfig(version='2025.02-pattern-v1', provider='pattern', languages=['en', 'es', 'pt', 'fr'], default_language='en', default_topic='general', entities=EntityPatterns(entries={'shared': [EntityPattern(label='ORG', pattern='NASA', alias=None, case_sensitive=False), EntityPattern(label='ORG', pattern='Google', alias=None, case_sensitive=False), EntityPattern(label='LOC', pattern='Mars', alias=None, case_sensitive=False), EntityPattern(label='ORG', pattern='ESA', alias=None, case_sensitive=False), EntityPattern(label='ORG', pattern='IMF', alias=None, case_sensitive=False), EntityPattern(label='ORG', pattern='ONU', alias=None, case_sensitive=False)], 'en': [EntityPattern(label='EVENT', pattern='Artemis II', alias=None, case_sensitive=False), EntityPattern(label='PRODUCT', pattern='Orion', alias=None, case_sensitive=False), EntityPattern(label='ORG', pattern='Wall Street', alias=None, case_sensitive=False)], 'es': [EntityPattern(label='ORG', pattern='Ministerio de Salud de Chile', alias=None, case_sensitive=False), EntityPattern(label='ORG', pattern='Universidad Nacional Autónoma de México', alias=None, case_sensitive=False), EntityPattern(label='ORG', pattern='Telefónica', alias=None, case_sensitive=False), EntityPattern(label='TECH', pattern='IA', alias='IA', case_sensitive=True)], 'pt': [EntityPattern(label='ORG', pattern='Universidade de São Paulo', alias=None, case_sensitive=False), EntityPattern(label='LOC', pattern='Amazônia', alias=None, case_sensitive=False)], 'fr': [EntityPattern(label='ORG', pattern='Agence spatiale européenne', alias=None, case_sensitive=False), EntityPattern(label='PRODUCT', pattern='Ariane 6', alias=None, case_sensitive=False)]}), topics={'space': TopicConfig(keywords={'shared': ['space', 'espacio', 'espaço', 'espace', 'lunar', 'orbit', 'orbital', 'rocket', 'cohete', 'foguete', 'fusée'], 'en': ['nasa', 'artemis', 'orion'], 'es': ['nasa', 'lunar'], 'pt': ['nasa', 'orbital'], 'fr': ['esa', 'ariane', 'européenne']}), 'science': TopicConfig(keywords={'shared': ['science', 'ciencia', 'ciência', 'scientifique', 'recherche', 'research', 'investigación', 'pesquisa', 'laboratorio', 'laboratory', 'laboratoire'], 'en': ['scientists', 'researchers'], 'es': ['investigadores', 'científicos', 'cientifico', 'científica', 'cientificos', 'cientificas', 'equipo científico'], 'pt': ['pesquisadores', 'cientistas', 'cientista'], 'fr': ['chercheurs', 'scientifiques']}), 'health': TopicConfig(keywords={'shared': ['health', 'salud', 'santé', 'sanitario'], 'en': ['ministry of health', 'hospital'], 'es': ['ministerio de salud', 'hospital'], 'pt': ['saúde', 'hospital'], 'fr': ['ministère de la santé', 'hôpital']}), 'technology': TopicConfig(keywords={'shared': ['technology', 'tecnología', 'tecnologia', 'technologie', 'ai', 'ia', 'inteligencia artificial', 'inteligência artificial'], 'en': ['platform', 'software'], 'es': ['plataforma', 'software'], 'pt': ['plataforma', 'software'], 'fr': ['plateforme', 'logiciel']}), 'climate': TopicConfig(keywords={'shared': ['climate', 'clima', 'climático', 'climática', 'climatique', 'emissions', 'emisiones', 'emissões', 'émissions', 'carbon', 'carbono', 'carbone'], 'en': ['climate', 'carbon'], 'es': ['emisiones', 'climática'], 'pt': ['climática', 'amazônia'], 'fr': ['climatique', 'carbone']}), 'economy': TopicConfig(keywords={'shared': ['economy', 'economía', 'economia', 'économie', 'market', 'mercado', 'marché', 'inflation', 'recession', 'recesión', 'recessão'], 'en': ['inflation', 'recession'], 'es': ['inflación', 'recesión'], 'pt': ['inflação', 'recessão'], 'fr': ['inflation', 'récession']})}, sentiment=SentimentConfig(default='neutral', tie_breaker='neutral', lexicon=SentimentLexicon(shared_positive=['confirmed', 'progress', 'celebrated', 'avance', 'avances', 'innovador', 'innovadora', 'soluciones', 'parceria', 'sucesso'], shared_negative=['warned', 'risk', 'crisis', 'preocupante', 'urgente', 'urgentes', 'inflation', 'recession', 'recesión', 'recessão'], languages={'en': SentimentLanguageLexicon(positive=['confirmed', 'progress', 'celebrated'], negative=['warned', 'recession', 'risk', 'negative']), 'es': SentimentLanguageLexicon(positive=['avance', 'celebró', 'soluciones', 'positivo', 'positiva'], negative=['alerta', 'preocupante', 'urgente', 'urgentes']), 'pt': SentimentLanguageLexicon(positive=['celebraram', 'parceria', 'inovador'], negative=['crise', 'alerta']), 'fr': SentimentLanguageLexicon(positive=['succès', 'avancée'], negative=['alerte', 'inquiétude'])})))} |  |  |  |
| news | NewsConfig |  |  |  |  |
| news.max_items | int | 50 | Maximum number of articles served per request. |  |  |
| news.default_language | str | "es" | Default language when none is specified by the user. |  | en |
| logging | LoggingConfig |  |  |  |  |
| logging.level | str | "INFO" | Minimum log level captured by the collector logger. |  | DEBUG |
| logging.file_path | Path | data/logs/collector.log | Absolute path of the rotating log file. |  |  |
| logging.max_file_size_mb | int | 10 | Maximum size per log file before rotation (MiB). |  |  |
| logging.retention_days | int | 30 | Number of days to keep rotated log files. |  |  |
| logging.format | str | "{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} | {message}" | Log formatting template compatible with structlog/loguru. |  |  |
