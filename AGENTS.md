# AGENTS.md — Python News Aggregator & Impact Scoring

> **Audience:** engineers and operators.
> **Purpose:** define the agents (workers/services), their contracts, SLAs, failure modes, metrics, and runbooks for a news collector/aggregator with an impact-scoring and ranking pipeline.
> **Style:** practical, testable, and reproducible. No essays—each agent has clear inputs/outputs, config, and checks.

---

## 0) System at a Glance

```
[Scheduler]
   └─▶ [Ingestion Agents (RSS/API/Scrape)]
            └─▶ [Parse & Normalize]
                     └─▶ [Canonicalize & Deduplicate]
                              └─▶ [Enrichment (NER/Topics/Sentiment/Geo)]
                                       └─▶ [Scoring]
                                                └─▶ [Rerank & Diversity]
                                                         └─▶ [Persist]
                                                                  ├─▶ [Serving API/UI]
                                                                  └─▶ [Eval & DQ Monitors]
                                                                          └─▶ [Alerts]
```

- **Messaging:** events over queues (e.g., Redis streams, RabbitMQ, Kafka) + idempotent upserts in DB.
- **Time:** store timestamps in **UTC**; display/local logic uses **America/Santiago**.
- **Idempotency:** every stage MUST be re-runnable without duplication (keys described below).
- **Robots/ToS:** all collectors MUST respect robots.txt and site ToS; keep a per-source policy file.
- **Efficiency:** cache aggressively (ETag/Last-Modified), minimize network requests, and batch wherever safe.

---

## 1) Shared Contracts

### 1.1 Event Envelope (v1)
```json
{
  "event_id": "uuid4",
  "type": "<stage.event>",
  "trace_id": "uuid4",
  "created_at": "2025-09-30T12:34:56Z",
  "payload": { /* stage specific */ },
  "retry_count": 0,
  "source": "ingestor:rss:nytimes",
  "schema_version": 1
}
```

### 1.2 Article Schema (v1)
```json
{
  "article_id": "sha256(content|title|pub_time|source_url)",
  "source_id": "string",
  "fetched_at": "ISO-UTC",
  "pub_time": "ISO-UTC (original if known)",
  "orig_tz": "IANA or null",
  "canonical_url": "https://...",
  "raw_url": "https://...",
  "title": "string",
  "summary": "short string or null",
  "content": "normalized text",
  "language": "iso639-1",
  "authors": ["..."],
  "topics": ["..."],
  "entities": [{"text": "...", "type": "ORG|PER|LOC|...", "salience": 0.0}],
  "sentiment": {"score": -1.0, "magnitude": 0.0},
  "geo": {"country": "CL", "admin1": "RM", "lat": -33.45, "lng": -70.66},
  "dedupe_cluster_id": "uuid4 or null",
  "score": 0.0,
  "score_explain": [{"feature": "recency_bonus", "value": 0.3}],
  "source_reliability": 0.0,
  "ingest_meta": {"user_agent": "...", "etag": "...", "last_modified": "..."}
}
```

### 1.3 Cluster Schema (v1)
```json
{
  "cluster_id": "uuid4",
  "members": ["article_id", "..."] ,
  "centroid_hash": "simhash-64",
  "title": "representative title",
  "topic": "string or null",
  "created_at": "ISO-UTC",
  "updated_at": "ISO-UTC"
}
```

### 1.4 Score Explanation Schema (v1)
```json
{
  "article_id": "...",
  "features": [
    {"name": "source_reliability", "value": 0.82},
    {"name": "recency_hours", "value": 3.1},
    {"name": "dedupe_penalty", "value": -0.15}
  ],
  "total": 0.73,
  "trace": "rule trail or model attributions"
}
```

---

## 2) Agent Directory (TL;DR)

| Agent | Purpose | Input | Output | Idempotency Key | Queue(s) |
|---|---|---|---|---|---|
| Scheduler | Triggers periodic jobs | cron | events | n/a | `cron.*` |
| Ingestion | Fetch RSS/APIs/scrapes with rate limits | source configs | raw docs | `source_id+url+etag/lastmod` | `ingest.raw` |
| Parse & Normalize | Clean HTML, extract text, dates, lang | raw docs | normalized articles | `source_id+canonical_url+hash(content)` | `ingest.norm` |
| Canonicalize & Dedupe | Canonical URL + SimHash/MinHash | normalized | article + cluster_id | `canonical_url` & `simhash` | `dedupe.out` |
| Enrichment | NER/topics/sentiment/geo | articles | enriched articles | `article_id+model_version` | `enrich.out` |
| Scoring | Compute impact score + explanation | enriched | scored articles | `article_id+scorer_version` | `score.out` |
| Rerank & Diversity | Top-K with caps and freshness | scored | ranked lists | `window_id+scorer_version` | `rank.out` |
| Persist | Upsert articles/clusters/snapshots | any | DB docs | primary keys | n/a |
| Serving | Read models for API/UI | DB | JSON responses | n/a | HTTP/gRPC |
| Eval | Offline metrics (NDCG@k etc.) | snapshots + labels | report | commit hash | `eval.out` |
| Data Quality | Detect drift/outages | telemetry | alerts | rule id | `alerts.dq` |
| Backfill | Safe re-ingest/re-score | commands | progress | run id | `backfill.*` |

Each agent below includes responsibilities, config, metrics, tests, and failure modes.

---

## 3) Agents

### 3.1 Scheduler & Orchestrator
**Responsibilities**
- Fire ingestion waves by source priority and freshness targets.
- Throttle by domain; pause sources on policy violations.

**Config**
- `CRON_INGEST_RSS`: `*/5 * * * *`
- `CRON_EVAL`: `0 */6 * * *`
- `MAX_CONCURRENT_JOBS`: `N`

**Metrics**
- Jobs launched/finished, queue lag, skipped due to rate limit.

**Failure Modes**
- Overlapping waves → use leases with TTL; dedupe by `run_id`.

**Tests**
- Property test: never schedule >X jobs per domain/min.

---

### 3.2 Ingestion Agent (RSS/API/Scrape)
**Responsibilities**
- Fetch with **ETag/If-None-Match** and **If-Modified-Since**. Respect robots.txt. Backoff with jitter. Distinct adapters per source.

**Input**
- Source config: `{url, kind, auth, rate_limit, policy}`

**Output**
- Raw document event: `{raw_html|json, headers, fetched_at}`

**Idempotency Key**
- `source_id + url + (etag || last_modified || date_floor_hour)`

**Config**
- `HTTP_TIMEOUT_S`: `10`
- `CONCURRENCY`: per-domain
- `USER_AGENT`: descriptive, contact email

**Metrics**
- p50/p95 fetch time, HTTP status mix, 304 hit rate, bytes saved, retries.

**Failure Modes**
- Blocked by bot protections → back off, mark **needs proxy** flag (manual approval).
- HTML atypical → pass through to parser; do not drop.

**Tests**
- Replay fixtures with ETag/Last-Modified; assert 304 path.

---

### 3.3 Parse & Normalize Agent
**Responsibilities**
- Extract main text, title, authors; strip boilerplate; decode/normalize; detect language; parse dates.
- Normalize timestamps to **UTC**; preserve `orig_tz`.

**Input**
- Raw doc

**Output**
- Normalized article (partial Article v1)

**Idempotency Key**
- `source_id + canonical_url + sha256(normalized_text)`

**Metrics**
- Parse success rate, avg content length, lang detection accuracy on labeled set.

**Tests**
- 20 tricky fixtures (encodings, paywalls, JS-heavy) → golden outputs.

**Failure Modes**
- Missing dates → derive from feed + content heuristics, mark `date_confidence`.

---

### 3.4 Canonicalize & Deduplicate Agent
**Responsibilities**
- Canonical URL rules: strip trackers (utm, fbclid), collapse AMP/mobile, normalize host/scheme.
- Exact dupes: `sha256` on normalized text.
- Near-dup: **SimHash/MinHash + LSH** on tokens; set `dedupe_cluster_id`.

**Config**
- `CANON_STRIP_PARAMS`: list
- `LSH_BANDS`, `SIMHASH_THRESHOLD`

**Metrics**
- Duplication rate, cluster count, precision/recall (labeled set).

**Tests**
- Positive/negative URL fixtures; confusion matrix for near-dup.

**Failure Modes**
- Over-merge: split clusters by title divergence; log anomalies.

---

### 3.5 Enrichment Agent (NER/Topics/Sentiment/Geo)
**Responsibilities**
- Add entities, topics, sentiment; coarse geo.
- Pin model versions; cache results; fall back for unsupported languages.

**Config**
- `NER_MODEL=vX.Y`, `TOPIC_MODEL=vA.B`, `SENTIMENT=vC.D`

**Metrics**
- Per-stage latency, cache hit, simple accuracy checks against golden set.

**Tests**
- 30 golden articles with expected labels; assert stable outputs.

**Failure Modes**
- Model timeouts → circuit breaker; retry on smaller batch.

---

### 3.6 Scoring Agent
**Responsibilities**
- Compute impact score from features (reliability, recency decay, entity/topic salience, duplication penalty, social signals if available).
- Produce **explanations** per item (feature contributions or rule trail).
- Deterministic given same inputs; versioned.

**Config**
- `SCORER_VERSION=YYYYMMDD`
- `DECAY_HALF_LIFE_H=12`
- `SOURCE_CAP_TOPK=0.4` (used downstream)

**Metrics**
- NDCG@k / Precision@k on dev set; p95 scoring latency.

**Tests**
- Golden eval: assert attributions and rank order across known cases.

**Failure Modes**
- Feature missing → default-safe values; emit metric.

---

### 3.7 Rerank & Diversity Agent
**Responsibilities**
- Enforce caps (max % per source), topic diversification, stable tie-breaking (recency > source > seeded random).
- Output ranked snapshot for a time window (e.g., last 6–12h).

**Config**
- `TOPK=50`, `MAX_PER_SOURCE=0.4`, `DIVERSITY_ALPHA=0.2`

**Metrics**
- Source concentration, topic entropy, freshness distribution.

**Tests**
- Synthetic set verifying caps and tie rules.

---

### 3.8 Persist Agent
**Responsibilities**
- Upsert articles, clusters, score explanations, and ranked snapshots.
- TTL policies on raw stages; compact historical partitions.

**Config**
- `TTL_RAW_DAYS=7`, `TTL_SNAPSHOTS_DAYS=90`

**Metrics**
- Upsert latency, write errors, compaction runtime, storage growth.

**Tests**
- Migration smoke tests; idempotent upsert replays.

---

### 3.9 Serving Agent (API/UI)
**Responsibilities**
- Serve paginated, filterable lists and item details; expose `why_ranked`.
- Health/readiness probes; rate-limited public endpoints.

**Contracts**
- `GET /v1/top?window=6h&k=50&topic=...&source=...&lang=...`
- `GET /v1/article/{id}` with `score_explain`

**Metrics**
- p50/p95 latency, error rates, cache hit, QPS.

**Tests**
- Contract tests + golden examples.

---

### 3.10 Evaluation Agent (Offline)
**Responsibilities**
- Compute NDCG@k, Precision@k, MRR per segment (source, lang, topic).
- Compare `SCORER_VERSION` vs baseline; produce report artifacts.

**Inputs**
- Snapshot + labeled/weak-labeled dev set.

**Outputs**
- Markdown/JSON report with ablations and significance notes.

**Metrics**
- Eval duration, coverage (labeled fraction), metric deltas.

**Tests**
- Determinism checks; schema validation of report.

---

### 3.11 Data Quality (DQ) & Drift Agent
**Responsibilities**
- Detect source outages, schema drift, sudden topic/language shifts, excess duplicates, stale top-K.
- Auto-suppress broken sources (cooldown) and alert.

**Config**
- Thresholds per signal; cooldown durations.

**Metrics**
- Alerts fired, MTTA, false positive rate.

**Tests**
- Replay historical outage; assert detection & suppression.

---

### 3.12 Backfill & Reindex Agent
**Responsibilities**
- Safe re-ingest or re-score after rule/model changes.
- Checkpoints, backpressure, and resumability.
- Never disturb live serving tables until cutover.

**Runbook**
1. Freeze scorer: tag `SCORER_VERSION`.
2. Write to shadow tables `*_v_next`.
3. Validate metrics on sample.
4. Swap aliases; archive old.

**Metrics**
- Backfill throughput, lag, errors, checkpoint progress.

**Tests**
- Dry-run on 1% partition; checksum counts match.

---

## 4) Queues, Topics & Storage

### 4.1 Suggested Queues/Topics
- `cron.ingest` – scheduler ticks
- `ingest.raw` – raw docs
- `ingest.norm` – normalized articles
- `dedupe.out` – deduped articles + clusters
- `enrich.out` – enriched articles
- `score.out` – scored articles
- `rank.out` – ranked snapshots
- `alerts.dq` – data quality alerts
- `backfill.ctrl` – backfill control commands

### 4.2 Storage Layout (example)
- `articles` (PK: `article_id`)
- `clusters` (PK: `cluster_id`)
- `rank_snapshots` (PK: `window_id`, `k`)
- `score_explanations` (PK: `article_id`, `scorer_version`)
- `source_policies` (PK: `source_id`)
- `ingest_raw_*` (TTL)

Indexes: by `pub_time`, `canonical_url`, `cluster_id`, `topics[]`, `language`, composite on (`pub_time`, `source_id`).

---

## 5) Configuration & Secrets

- `.env`-style vars for local; secrets live in Vault/Secret Manager in prod.
- Rotate keys quarterly; never commit secrets.
- Per-source policy file with contact email and crawl budget.

**Key Vars**
```
USER_AGENT="NewsImpactBot/1.0 (+contact@example.com)"
HTTP_TIMEOUT_S=10
PER_DOMAIN_QPS=0.2
AMERICA_SANTIAGO_TZ="America/Santiago"
SCORER_VERSION=2025-09-30
DECAY_HALF_LIFE_H=12
TOPK=50
MAX_PER_SOURCE=0.4
```

---

## 6) SLOs & KPIs

| Area | SLO | KPI | Alert | Owner |
|---|---|---|---|---|
| Ingest → Visible | p95 < **N** minutes @ 1k articles/hour | pipeline latency | warn at 0.8×, page at 1.2× | on-call |
| Dedupe Quality | Near-dup F1 ≥ **0.95** | precision/recall | warn <0.93 | ML |
| Ranking Freshness | ≥ **80%** of top-K < 12h old | freshness ratio | warn <70% | product |
| Diversity | Any source ≤ **40%** in top-K | source share | warn >45% | product |
| Serving | p95 < **250 ms**, error < **0.5%** | latency/error | page at 1% | platform |

> Tune `N` to your infra; start with 10–15 minutes for a lean stack.

---

## 7) Observability

- **Structured logs** at each stage: include `trace_id`, `article_id`, `source_id`, timings, sizes, and decisions (e.g., "dedupe=merge cluster_id=...").
- **Metrics**: counters (ingested, deduped, enriched), histograms (latency), gauges (queue lag), percentiles.
- **Tracing**: one span per stage, propagate `trace_id` across.

Dashboards: ingest rate, queue lag, dedupe F1 (rolling), freshness, source concentration, serving latency.

---

## 8) Testing Matrix

- **Unit:** URL rules, parsers, scoring functions (deterministic).
- **Property-based:** parsers never return empty for valid HTML; canonicalization idempotent.
- **Golden tests:** 50 articles locked to expected entities/topics/scores.
- **Load tests:** N sources × M articles with realistic errors.
- **Chaos:** kill a worker mid-run; ensure no dupes and job resumes.

---

## 9) Failure Modes & DLQs

- Each agent writes to a **Dead Letter Queue** with `{event, error, last_stage, retries}`.
- Automatic retry policy with exponential backoff; cap retries; emit alert at threshold.
- Operators can replay DLQ after a code/config fix.

---

## 10) Security & Compliance

- Respect robots.txt; keep a cached snapshot per source and revalidate daily.
- Track ToS notes (allowed endpoints, rate limits).
- SBOM/dependency audit on every build; secret scanning pre-commit and in CI.
- PII: store only what is necessary; redact before logs.

---

## 11) Deployment & Rollout

- **Versioning:** tag each agent image `YYYYMMDD.sha`.
- **Blue/Green for scorer & ranking:** write to shadow tables, compare metrics, then cut over.
- **Autoscaling:** scale ingestors by queue depth; cap per-domain concurrency.

---

## 12) Local Dev & Make Targets (example)

```
make bootstrap         # create venv, install deps, pre-commit hooks
make run-pipeline      # start minimal pipeline (local queues + DB)
make ingest N=100      # fetch sample
make eval              # run offline metrics
make lint              # ruff + mypy + bandit
make test              # pytest + coverage
make prof              # profile a pipeline slice
```

---

## 13) Operational Runbooks (high-level)

### 13.1 Pipeline Slowness
1) Check queue lag dashboards; identify the stage bottleneck.
2) Inspect p95 span times; profile if a regression.
3) Scale the slow agent replicas; verify DB headroom.
4) If parsing, reduce concurrency for problematic domains temporarily.

### 13.2 Duplicate Flood
1) Inspect canonicalization rules; recent URL param change?
2) Lower `SIMHASH_THRESHOLD` temporarily; re-cluster recent window.
3) Patch rules; run backfill on last 48h.

### 13.3 Stale Top-K
1) Check scheduler health and ingestion 304 ratio (too high?).
2) Verify scorer decay settings; recent version change?
3) Run eval; compare to baseline; roll back if necessary.

---

## 14) Optional LLM-Backed Agents (if enabled)

- **Headline/Summary Agent:** produce concise summaries; bounded token budgets; prompt pinned and versioned.
- **Explainability Agent:** turn `score_explain` features into a human-friendly "Why this matters" line.
- **Safety:** deterministic prompts, profanity/PII filters; cost guardrails.

> If LLMs are off, keep these fields null.

---

## 15) Glossary

- **Idempotency:** running the same job twice yields one stored result.
- **Shadow table:** a parallel write target used before cutover.
- **Near-dup:** articles with high textual overlap but different URLs.

---

## 16) Checklists

- [ ] Robots.txt respected & cached per source
- [ ] ETag/If-Modified-Since implemented
- [ ] Canonical URL rules with tests
- [ ] SimHash/MinHash thresholds tuned
- [ ] Enrichment models versioned & cached
- [ ] Scorer deterministic & explained
- [ ] Diversity caps active
- [ ] DLQs wired and replayable
- [ ] SLO dashboards & alerts live
- [ ] Backfill runbook tested on 1% partition

---

**End of AGENTS.md**
