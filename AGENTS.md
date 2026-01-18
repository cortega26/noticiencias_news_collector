# AGENTS.md --- Noticiencias News Collector

> **Audience:** developers, data engineers, and AI agents maintaining
> the Noticiencias scientific news aggregation stack.\
> **Purpose:** define architecture, contracts, operational workflow and
> ---critically--- **anti‑regression guardrails** so the system only
> moves forward without breaking what already works.

------------------------------------------------------------------------

## 0) Architecture Snapshot

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

-   **Messaging:** local dev uses in‑memory queues; production may swap
    to Redis Streams/Kafka. Payloads must be idempotent.\
-   **Time:** persist in **UTC**; convert to America/Santiago only at
    presentation layer.\
-   **Configuration:** YAML in `config/`; secrets via environment
    variables only.\
-   **Idempotency:** canonical URL hash is the primary key; every stage
    must accept replays safely.

------------------------------------------------------------------------

## 1) Shared Contracts & Schemas

### Event Envelope (v1)

``` json
{
  "event_id": "uuid4",
  "stage": "collector.fetch | enrichment.ner | ...",
  "trace_id": "uuid4",
  "created_at": "ISO-UTC",
  "payload": {},
  "retry_count": 0,
  "source": "collector:rss:esa",
  "schema_version": 1
}
```

### Article Entity (v2)

``` json
{
  "article_id": "sha256(title|canonical_url|published_at)",
  "source_id": "str",
  "fetched_at": "ISO-UTC",
  "published_at": "ISO-UTC or null",
  "canonical_url": "https://...",
  "title": "str",
  "content": "normalized str",
  "language": "iso639-1",
  "authors": [],
  "topics": [],
  "dedupe_cluster_id": "uuid4 | null",
  "impact_score": 0.0
}
```

------------------------------------------------------------------------

## 2) Agent Directory

(Modules and responsibilities remain as previously defined:
Orchestrator, Collectors, Parser, Dedupe, Enrichment, Scoring, Reranker,
Storage, Serving, Monitoring.)

------------------------------------------------------------------------

## 3) Coding Standards

-   Python 3.13+, typing mandatory on public interfaces.\
-   PEP‑8 + ruff; dataclasses for structured data.\
-   Structured logging with trace_id and stage.\
-   Never swallow exceptions.\
-   Datetimes always timezone.utc.\
-   Async collectors must respect rate limits.\
-   Every behavior change requires tests and docs.

------------------------------------------------------------------------

## 4) **REGRESSION GUARDRAILS (CORE SECTION)**

### RG0 --- Golden Rule

**No bug is fixed without at least one regression test** that fails
before the fix and passes after.

### RG1 --- Definition of Done

A PR is complete only if it: - Includes regression tests for any bug
fix\
- Passes lint + typecheck + tests\
- Does not alter unrelated behavior\
- Documents: **Symptom → Root Cause → Fix → Test**

### RG2 --- Small Reversible PRs

-   Max **2 core files** per PR (`system.py`, collectors, storage).\
-   No mega‑refactors while unstable.

### RG3 --- No Mixed Refactor + Feature

New collector/features must be shipped first with tests; architectural
cleanup comes in later PRs.

### RG4 --- Standardized Failure Stages

Errors must be tagged with: - collector.fetch\
- collector.parse\
- collector.validate_payload\
- collector.apply_filters\
- storage.upsert\
- system.orchestrate

### RG5 --- Validation Error Logging

On model validation failure log: - stage, source_id, collector_type\
- `e.errors()` details\
- example title/url\
- safe metrics like `len(content)`

### RG6 --- Source Health Report

Each run must generate: `data/exports/source_health.json` with
per‑source counters: fetch_ok, parsed_ok, validation_ok, saved, and
primary failure reason.

### RG7 --- Testing Layers (Order)

1)  Contract tests\
2)  Invariants\
3)  Golden tests\
4)  Smoke tests (fixtures, no real network)

### RG8 --- Network Policy

Default suite must not depend on real network/headless.

### RG9 --- Green Baseline First

If unstable, revert to last green commit before new work.

------------------------------------------------------------------------

## 5) Local Development

-   `python -m venv .venv`\
-   `pip install -r requirements.lock`\
-   `pytest` / `ruff check` / `mypy src`

------------------------------------------------------------------------

## 6) Observability & Ops

-   Track ingest latency, dedupe F1, freshness, diversity.\
-   Alerts on backlog and scoring drift.

------------------------------------------------------------------------

## 7) Deployment

-   Docker versioned images\
-   Blue/green for scoring\
-   Feature flags in `config/features.yaml`

------------------------------------------------------------------------

## 8) Checklists

-   ETag implemented\
-   Canonical rules tested\
-   Dedupe tuned\
-   DLQ replay verified\
-   **Regression tests present for every fix**

------------------------------------------------------------------------

**End of AGENTS.md --- Unified & Regression‑Safe**
