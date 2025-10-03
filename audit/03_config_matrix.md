# Phase 3 — Configuration Surface & Precedence Validation

## Key inventory

### `config.toml`
```
app.debug
app.environment
app.timezone
collection.async_enabled
collection.collection_interval_hours
collection.max_articles_per_source
collection.max_concurrent_requests
collection.recent_days_threshold
collection.request_timeout_seconds
collection.user_agent
collection.canonicalization_cache_size
database.connect_timeout
database.driver
database.host
database.max_overflow
database.name
database.path
database.pool_recycle
database.pool_size
database.pool_timeout
database.port
database.sslmode
database.statement_timeout
database.user
dedup.simhash_candidate_window
dedup.simhash_threshold
enrichment.analysis_cache_size
enrichment.default_model
enrichment.models.pattern_v1.default_language
enrichment.models.pattern_v1.default_topic
enrichment.models.pattern_v1.entities.entries.en
enrichment.models.pattern_v1.entities.entries.es
enrichment.models.pattern_v1.entities.entries.fr
enrichment.models.pattern_v1.entities.entries.pt
enrichment.models.pattern_v1.entities.entries.shared
enrichment.models.pattern_v1.languages
enrichment.models.pattern_v1.provider
enrichment.models.pattern_v1.sentiment.default
enrichment.models.pattern_v1.sentiment.lexicon.languages.en.negative
enrichment.models.pattern_v1.sentiment.lexicon.languages.en.positive
enrichment.models.pattern_v1.sentiment.lexicon.languages.es.negative
enrichment.models.pattern_v1.sentiment.lexicon.languages.es.positive
enrichment.models.pattern_v1.sentiment.lexicon.languages.fr.negative
enrichment.models.pattern_v1.sentiment.lexicon.languages.fr.positive
enrichment.models.pattern_v1.sentiment.lexicon.languages.pt.negative
enrichment.models.pattern_v1.sentiment.lexicon.languages.pt.positive
enrichment.models.pattern_v1.sentiment.lexicon.shared_negative
enrichment.models.pattern_v1.sentiment.lexicon.shared_positive
enrichment.models.pattern_v1.sentiment.tie_breaker
enrichment.models.pattern_v1.topics.climate.keywords.en
enrichment.models.pattern_v1.topics.climate.keywords.es
enrichment.models.pattern_v1.topics.climate.keywords.fr
enrichment.models.pattern_v1.topics.climate.keywords.pt
enrichment.models.pattern_v1.topics.climate.keywords.shared
enrichment.models.pattern_v1.topics.economy.keywords.en
enrichment.models.pattern_v1.topics.economy.keywords.es
enrichment.models.pattern_v1.topics.economy.keywords.fr
enrichment.models.pattern_v1.topics.economy.keywords.pt
enrichment.models.pattern_v1.topics.economy.keywords.shared
enrichment.models.pattern_v1.topics.health.keywords.en
enrichment.models.pattern_v1.topics.health.keywords.es
enrichment.models.pattern_v1.topics.health.keywords.fr
enrichment.models.pattern_v1.topics.health.keywords.pt
enrichment.models.pattern_v1.topics.health.keywords.shared
enrichment.models.pattern_v1.topics.science.keywords.en
enrichment.models.pattern_v1.topics.science.keywords.es
enrichment.models.pattern_v1.topics.science.keywords.fr
enrichment.models.pattern_v1.topics.science.keywords.pt
enrichment.models.pattern_v1.topics.science.keywords.shared
enrichment.models.pattern_v1.topics.space.keywords.en
enrichment.models.pattern_v1.topics.space.keywords.es
enrichment.models.pattern_v1.topics.space.keywords.fr
enrichment.models.pattern_v1.topics.space.keywords.pt
enrichment.models.pattern_v1.topics.space.keywords.shared
enrichment.models.pattern_v1.topics.technology.keywords.en
enrichment.models.pattern_v1.topics.technology.keywords.es
enrichment.models.pattern_v1.topics.technology.keywords.fr
enrichment.models.pattern_v1.topics.technology.keywords.pt
enrichment.models.pattern_v1.topics.technology.keywords.shared
enrichment.models.pattern_v1.version
enrichment.result_cache_size
logging.file_path
logging.format
logging.level
logging.max_file_size_mb
logging.retention_days
news.default_language
news.max_items
paths.data_dir
paths.dlq_dir
paths.logs_dir
rate_limiting.backoff_base
rate_limiting.backoff_max
rate_limiting.delay_between_requests_seconds
rate_limiting.domain_default_delay_seconds
rate_limiting.domain_overrides.arxiv.org
rate_limiting.domain_overrides.export.arxiv.org
rate_limiting.domain_overrides.reddit.com
rate_limiting.domain_overrides.www.reddit.com
rate_limiting.jitter_max
rate_limiting.max_retries
rate_limiting.retry_delay_seconds
robots.cache_ttl_seconds
robots.respect_robots
scoring.content_quality_heuristics.entity_target_count
scoring.content_quality_heuristics.summary_length_divisor
scoring.content_quality_heuristics.title_length_divisor
scoring.content_quality_heuristics.weights.entity
scoring.content_quality_heuristics.weights.summary
scoring.content_quality_heuristics.weights.title
scoring.daily_top_count
scoring.diversity_penalty.max_penalty
scoring.diversity_penalty.weight
scoring.engagement_heuristics.external_weight
scoring.engagement_heuristics.fallback_sentiment
scoring.engagement_heuristics.length_weight
scoring.engagement_heuristics.sentiment_scores.negative
scoring.engagement_heuristics.sentiment_scores.neutral
scoring.engagement_heuristics.sentiment_scores.positive
scoring.engagement_heuristics.word_count_divisor
scoring.feature_weights.content_quality
scoring.feature_weights.engagement
scoring.feature_weights.freshness
scoring.feature_weights.source_credibility
scoring.freshness.half_life_hours
scoring.freshness.max_decay_hours
scoring.minimum_score
scoring.mode
scoring.reranker_seed
scoring.source_cap_percentage
scoring.topic_cap_percentage
scoring.weights.content_quality
scoring.weights.engagement_potential
scoring.weights.recency
scoring.weights.source_credibility
scoring.workers
text_processing.boost_keywords
text_processing.min_content_length
text_processing.penalty_keywords
text_processing.supported_languages
```

### `.env.example`
```
ENV
APP_ENV
ENVIRONMENT
DEBUG
LOG_LEVEL
COLLECTION_INTERVAL
REQUEST_TIMEOUT
ASYNC_ENABLED
MAX_CONCURRENT_REQUESTS
MAX_ARTICLES_PER_SOURCE
RECENT_DAYS_THRESHOLD
REQUEST_DELAY
DOMAIN_DEFAULT_DELAY
MAX_RETRIES
RETRY_DELAY
BACKOFF_BASE
BACKOFF_MAX
JITTER_MAX
RESPECT_ROBOTS
ROBOTS_CACHE_TTL
WEIGHT_SOURCE
WEIGHT_RECENCY
WEIGHT_CONTENT
WEIGHT_ENGAGEMENT
DAILY_TOP_COUNT
MINIMUM_SCORE
SCORING_MODE
FEATURE_WEIGHT_SOURCE
FEATURE_WEIGHT_FRESHNESS
FEATURE_WEIGHT_CONTENT
FEATURE_WEIGHT_ENGAGEMENT
SCORING_WORKERS
FRESHNESS_HALF_LIFE_HOURS
FRESHNESS_MAX_DECAY_HOURS
DIVERSITY_PENALTY_WEIGHT
DIVERSITY_MAX_PENALTY
SCORING_TITLE_LENGTH_DIVISOR
SCORING_SUMMARY_LENGTH_DIVISOR
SCORING_ENTITY_TARGET_COUNT
SCORING_CONTENT_WEIGHT_TITLE
SCORING_CONTENT_WEIGHT_SUMMARY
SCORING_CONTENT_WEIGHT_ENTITY
SCORING_SENTIMENT_POSITIVE
SCORING_SENTIMENT_NEGATIVE
SCORING_SENTIMENT_NEUTRAL
SCORING_SENTIMENT_FALLBACK
SCORING_WORD_COUNT_DIVISOR
SCORING_ENGAGEMENT_EXTERNAL_WEIGHT
SCORING_ENGAGEMENT_LENGTH_WEIGHT
RERANKER_SEED
SOURCE_CAP_PERCENTAGE
TOPIC_CAP_PERCENTAGE
MIN_CONTENT_LENGTH
ENRICHMENT_MODEL_KEY
ENRICHMENT_PROVIDER
ENRICHMENT_ANALYSIS_CACHE
ENRICHMENT_RESULT_CACHE
ENRICHMENT_MODEL_VERSION
SIMHASH_THRESHOLD
SIMHASH_CANDIDATE_WINDOW
HEALTHCHECK_MAX_PENDING
HEALTHCHECK_MAX_INGEST_MINUTES
AUDIT_TODOS_MAX_NEW
```

> **Observation:** `.env.example` uses historical short variable names without the `NOTICIENCIAS__` prefix. They are ignored by `noticiencias.config_manager` and require translation to the nested convention showcased below.

## Precedence matrix

| Config path | Default (`DEFAULT_CONFIG`) | `config.toml` override | `.env` override | Process env override | Resolved value | Winning layer |
| --- | --- | --- | --- | --- | --- | --- |
| `app.environment` | `development` | `staging` | `production` | `test` | `test` | Process environment |
| `collection.async_enabled` | `false` | `true` | `false` | — | `false` | `.env` file |
| `rate_limiting.max_retries` | `3` | `7` | `9` | — | `9` | `.env` file |
| `database.driver` | `sqlite` | `postgresql` | — | — | `postgresql` | `config.toml` |

## Sample `.env` used in tests

```
NOTICIENCIAS__APP__ENVIRONMENT=production
NOTICIENCIAS__COLLECTION__ASYNC_ENABLED=false
NOTICIENCIAS__RATE_LIMITING__MAX_RETRIES=9
```

The tests additionally set `NOTICIENCIAS__APP__ENVIRONMENT=test` in the process environment to confirm that runtime variables sit at the top of the precedence order.
