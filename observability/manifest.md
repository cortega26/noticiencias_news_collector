# Observabilidad del Pipeline de Noticias

## Campos de logging estructurado

| Stage | Event | Campos clave |
| --- | --- | --- |
| `pipeline` | `cycle.start`, `cycle.completed` | `session_id`, `system_id`, `duration_seconds`, `error_rate`, `sources_filter` |
| `ingestion` | `batch.start`, `batch.completed` | `collector`, `sources`, `sources_processed`, `errors`, `duration_seconds` |
| `ingestion` | `source_processed` | `source_id`, `collector`, `articles_found`, `articles_saved`, `latency_ms`, `trace_id` |
| `dedupe` | `dedupe_outcome` | `article_id`, `cluster_id`, `confidence`, `outcome` |
| `scoring` | `batch_statistics`, `article_scored` | `articles_scored`, `articles_included`, `articles_excluded`, `average_score`, `final_score` |
| `ranking` | `selection_summary`, `freshness_ratio_updated` | `selected_count`, `freshness_ratio` |
| `slo` | `evaluation` | `slo`, `value`, `status`, `target`, `warning`, `critical` |

Todos los eventos incluyen `stage` y `event` para facilitar filtrado en SIEM.

## Métricas instrumentadas

| Métrica | Tipo | Etiquetas | Descripción |
| --- | --- | --- | --- |
| `news_ingest_sources_total` | Counter | `source_id`, `outcome` | Fuentes procesadas con éxito/error. |
| `news_ingest_articles_total` | Counter | `source_id`, `status` | Artículos detectados vs guardados por fuente. |
| `news_pipeline_stage_latency_seconds` | Histogram | `stage` | Latencia de etapas (`pipeline.*`, `ingestion.source`, etc.). |
| `news_pipeline_visibility_latency_seconds` | Histogram | — | Tiempo ingestión→visible para SLO. |
| `news_pipeline_errors_total` | Counter | `stage`, `error_type` | Clasificación de errores operativos. |
| `news_dedupe_outcomes_total` | Counter | `outcome` | Nuevos artículos, duplicados exactos o cercanos. |
| `news_pipeline_queue_lag_seconds` | Gauge | `stage` | Retraso de colas configurables. |
| `news_pipeline_topk_freshness_ratio` | Gauge | — | Porción reciente del top-K. |
| `news_pipeline_active_traces` | Gauge | — | Ciclos concurrentes observados. |

## Spans de tracing

- `pipeline.cycle` (root) con atributos `session_id`, `system_id`, `dry_run`, `sources_filter`.
- Sub-spans `pipeline.ingestion`, `pipeline.scoring`, `pipeline.ranking`, `pipeline.reporting`.
- Spans anidados por fuente `ingestion.source` (atributos `source_id`, `collector`).
- Eventos de error registrados como `record_exception` y status `ERROR`.

## SLOs y alertas

- **Ingest → Visible p95 < 15 min** (`news_pipeline_visibility_latency_seconds`).
- **Error rate < 1%** (ratio entre `news_pipeline_errors_total` y `news_ingest_sources_total`).
- **Freshness top-K ≥ 80%** (`news_pipeline_topk_freshness_ratio`).
- **Dedupe effectiveness ≥ 0.95** (`news_dedupe_outcomes_total`).

Las reglas de alerta en `observability/alerts/pipeline_alerts.yaml` se alinean con estos SLOs y definen severidades críticas/aviso.

## Dashboards

- `observability/dashboards/pipeline_overview.json` exporta un tablero Grafana con paneles de tasa de ingestión, deduplicación, frescura y clases de error.

## Integración

- `ObservabilityManager` inicializa OpenTelemetry + métricas Prometheus y expone métodos `instrument_stage`, `record_*` y `evaluate_slos`.
- `main.py` envuelve cada fase del pipeline en spans, registra métricas y adjunta evaluaciones SLO al reporte.
- `BaseCollector` y `DatabaseManager` actualizan counters/gauges relevantes y generan logs estructurados por evento.
