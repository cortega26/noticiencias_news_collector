# AGENTS.md — Noticiencias News Collector

> **Audience:** developers, data engineers, and operators who maintain the Noticiencias scientific news aggregation stack.
> **Purpose:** describe the core agents, how they interact, and the guardrails for building, testing, and operating the system.
> **Style:** concise, actionable, and project-specific. Every instruction should be testable or automatable.

---

## 0) Architecture Snapshot

```
[Scheduler]
  └─▶ [collectors]
          └─▶ [utils.parse] → [collectors.parsers]
                  └─▶ [utils.dedupe]
                          └─▶ [enrichment]
                                  └─▶ [scoring]
                                          └─▶ [reranker]
                                                  └─▶ [storage]
                                                          ├─▶ [serving]
                                                          └─▶ [monitoring]
```

- **Messaging:** in local dev we rely on in-memory queues; in production swap to Redis Streams or Kafka. Keep payloads idempotent.
- **Time:** persist and compare timestamps in **UTC**; conversions to **America/Santiago** happen only inside presentation layers.
- **Configuration:** `config/` contains YAML files per environment; keep secrets in environment variables, never in the repo.
- **Idempotency:** every stage must accept replays without duplication. Rely on canonical URL hashes as primary keys.

---

## 1) Shared Contracts & Schemas

### 1.1 Event Envelope (v1)
```json
{
  "event_id": "uuid4",
  "stage": "collector.fetch" | "enrichment.ner" | ...,
  "trace_id": "uuid4",
  "created_at": "2025-02-01T12:34:56Z",
  "payload": {},
  "retry_count": 0,
  "source": "collector:rss:esa",
  "schema_version": 1
}
```

### 1.2 Article Entity (v2)
```json
{
  "article_id": "sha256(title|canonical_url|published_at)",
  "source_id": "str",
  "fetched_at": "ISO-UTC",
  "published_at": "ISO-UTC or null",
  "canonical_url": "https://...",
  "raw_url": "https://...",
  "title": "str",
  "summary": "str | null",
  "content": "normalized str",
  "language": "iso639-1",
  "authors": ["..."] ,
  "topics": ["..."] ,
  "entities": [{"text": "...", "type": "ORG|PER|LOC|...", "salience": 0.0}],
  "sentiment": {"score": -1.0, "magnitude": 0.0},
  "geo": {"country": "CL", "admin1": "RM", "lat": -33.45, "lng": -70.66},
  "dedupe_cluster_id": "uuid4 | null",
  "impact_score": 0.0,
  "score_breakdown": [{"feature": "recency_bonus", "value": 0.3}],
  "reliability": 0.0,
  "ingest_meta": {"etag": "...", "last_modified": "...", "user_agent": "..."}
}
```

### 1.3 Cluster Record (v1)
```json
{
  "cluster_id": "uuid4",
  "members": ["article_id", "..."],
  "centroid_hash": "simhash-64",
  "title": "representative title",
  "topic": "string | null",
  "created_at": "ISO-UTC",
  "updated_at": "ISO-UTC"
}
```

### 1.4 Score Explanation (v1)
```json
{
  "article_id": "...",
  "features": [{"name": "source_reliability", "value": 0.82} , ...],
  "total": 0.73,
  "trace": "human-readable explanation"
}
```

---

## 2) Agent Directory

| Agent | Module(s) | Purpose | Input | Output | Idempotency Key | Queue/Trigger |
|---|---|---|---|---|---|---|
| Scheduler | `scripts/scheduler.py` | Cron-style job orchestration | cron | job events | N/A | `cron.*` |
| Collectors | `src/collectors/*` | Fetch RSS/APIs, respect rate limits | source config | raw docs | `source_id+url+etag/lastmod` | `ingest.raw` |
| Parser & Normalizer | `src/utils/text_cleaner.py`, `src/collectors/parsers.py` | Clean HTML, extract metadata | raw docs | normalized article | `source_id+canonical_url+hash(content)` | `ingest.norm` |
| Canonicalize & Dedupe | `src/utils/dedupe.py`, `tests/test_dedupe_utils.py` | Resolve canonical URLs, detect near-dups | normalized | article + cluster | `canonical_url` + `simhash` | `dedupe.out` |
| Enrichment | `src/enrichment/*` | Topics, NER, sentiment, geo | article | enriched article | `article_id+model_version` | `enrich.out` |
| Scoring | `src/scoring/*` | Compute impact score & reasons | enriched article | scored article | `article_id+scorer_version` | `score.out` |
| Reranker | `src/reranker/*` | Diversify and order top stories | scored list | reranked list | `window_id+scorer_version` | `rank.out` |
| Storage | `src/storage/*` | Upsert into persistence layer | pipeline outputs | DB docs | primary keys | N/A |
| Serving | `src/serving/*` | API/UI payloads | DB + caches | JSON responses | N/A | HTTP/gRPC |
| Monitoring | `scripts/monitor_*` (future) | Metrics, alerts | telemetry | alerts | rule id | `alerts.*` |

---

## 3) Coding Standards

- **Python Version:** 3.10+. Use `typing` (e.g., `TypedDict`, `Protocol`) for all public interfaces.
- **Style:** PEP 8 + `ruff` defaults. Prefer dataclasses for structured data and `pydantic` models in serving layer.
- **Logging:** `structlog`-style dictionaries with `trace_id`, `article_id`, `source_id`, latency, and key decisions.
- **Error handling:** never swallow exceptions; wrap with contextual message and re-raise or push to DLQ.
- **Time:** use `datetime.datetime` with `timezone.utc`; avoid naive datetimes.
- **Concurrency:** collectors must honor `config/rate_limits.yaml`. Use `asyncio` for network-bound collectors when possible.
- **Testing:** every new module needs matching tests in `tests/`. For bug fixes, add regression tests.
- **Docs:** update `docs/` or module docstrings when behavior changes.

---

## 4) Local Development

- Create a virtual environment: `python -m venv .venv && source .venv/bin/activate`.
- Install dependencies: `pip install -r requirements.txt`.
- Sample commands:
  - `python run_collector.py --sources config/sources.yaml` — end-to-end pipeline run.
  - `pytest` — full test suite (fast, runs under 2 minutes on laptop).
  - `ruff check src tests` — lint.
  - `mypy src` — type check.
- Keep `tests/data/` fixtures lightweight and anonymized.

---

## 5) Observability & Ops

- **Metrics:** ingestion throughput, dedupe precision/recall, enrichment latency, reranker freshness, API p95/p99.
- **Dashboards:** maintain Grafana boards for queue lag, error rates, DLQ depth, and scoring drift.
- **Tracing:** propagate `trace_id` end-to-end; use OpenTelemetry exporters behind a feature flag.
- **Alerts:**
  - Pipeline ingest-to-visible p95 < **15 min** (warn at 12, page at 18).
  - Dedupe near-dup F1 ≥ **0.95** (warn <0.93).
  - Top-K freshness: ≥ **80%** of surfaced articles < 12h old.
  - Source diversity: any provider ≤ **40%** of top-K (warn at 45%).

---

## 6) Testing Matrix

- **Unit:** URL canonicalization, rate limiting, text cleaning, scoring functions.
- **Property-based:** canonicalization idempotency, dedupe similarity thresholds stable under whitespace changes.
- **Golden tests:** curated set of 50 articles verifying enrichment, scoring, and reranking outputs.
- **Load:** replay last 24h for top 10 sources; ensure no backlog or CPU thrash.
- **Chaos:** kill a collector mid-run; verify idempotent reprocessing.

---

## 7) Failure Modes & Runbooks

- **Collector outage:** check rate-limit config, and HTTP errors. Fall back to cached ETag if available.
- **Duplicate flood:** inspect `utils/url_canonicalizer.py`; adjust regex rules and reprocess last 48h.
- **Stale ranking:** verify scheduler health and scoring decay parameters; run `pytest tests/test_reranker.py` before rollout.
- **Enrichment drift:** compare embedding/topic distributions; retrain or roll back model version.

---

## 8) Security & Compliance

- Strip PII before logging or persisting; redact emails and phone numbers.
- Run SBOM/dependency scan in CI; fail build on high-severity vulnerabilities.
- API auth (serving layer) via OAuth2 bearer tokens; rotate keys every 90 days.

---

## 9) Deployment & Release

- Version Docker images as `noticiencias/<agent>:YYYYMMDD.<short_sha>`.
- Blue/green deployments for scoring and reranking stages; write to shadow tables first.
- Feature flags live in `config/features.yaml`; document defaults and rollout plan.
- After deploy, monitor alerts for 1 hour; create post-deploy note in ops log.

---

## 10) Checklists

- [ ] ETag/If-Modified-Since implemented in collectors
- [ ] Canonical URL rules tested (`pytest tests/test_url_canonicalizer.py`)
- [ ] SimHash thresholds tuned and regression-tested
- [ ] Enrichment models versioned & cached locally
- [ ] Scoring deterministic, explanations stored
- [ ] Diversity guardrails active in reranker
- [ ] DLQ replay tooling verified weekly
- [ ] Observability dashboards & alerts green
- [ ] Backfill runbook tested on 1% sample monthly

---

**End of AGENTS.md**
