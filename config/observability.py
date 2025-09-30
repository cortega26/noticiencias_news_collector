"""Configuración centralizada de observabilidad y SLOs."""

from __future__ import annotations

from typing import Any, Dict, List


OBSERVABILITY_CONFIG: Dict[str, Any] = {
    "service_name": "noticiencias-news-collector",
    "service_namespace": "news-pipeline",
    "environment": "local",
    "tracing": {
        "exporter": "console",  # Puede cambiarse a otlp/http en despliegues reales
        "sample_ratio": 1.0,
    },
    "metrics": {
        "registry": "prometheus",
        "visibility_latency_buckets_seconds": [60, 120, 180, 300, 600, 900],
        "stage_latency_buckets_seconds": [1, 2, 5, 10, 30, 60, 120],
    },
    "freshness": {"target_hours": 12},
}


SLO_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "ingest_to_visible_minutes": {
        "target": 15,
        "warning": 12,
        "critical": 18,
        "description": "Tiempo desde la ingestión hasta que un artículo aparece en el top-K",
    },
    "pipeline_error_rate": {
        "target": 0.005,
        "warning": 0.008,
        "critical": 0.012,
        "description": "Errores por etapa del pipeline sobre fuentes procesadas",
    },
    "topk_freshness_ratio": {
        "target": 0.8,
        "warning": 0.7,
        "critical": 0.6,
        "description": "Proporción de artículos del top-K con menos de 12h de antigüedad",
    },
    "dedupe_effectiveness": {
        "target": 0.95,
        "warning": 0.92,
        "critical": 0.9,
        "description": "Proporción de duplicados detectados correctamente",
    },
}


ALERT_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "PipelineLatencyBreached",
        "metric": "news_pipeline_visibility_latency_seconds",
        "aggregation": "p95",
        "threshold": 900,
        "severity": "critical",
        "description": "Ingesta a visible supera 15 minutos",
    },
    {
        "name": "PipelineErrorRateHigh",
        "metric": "news_pipeline_errors_total",
        "aggregation": "rate5m",
        "threshold": 0.01,
        "severity": "critical",
        "description": "Errores del pipeline superan el 1% del tráfico",
    },
    {
        "name": "FreshnessDegradation",
        "metric": "news_pipeline_topk_freshness_ratio",
        "aggregation": "avg15m",
        "threshold": 0.7,
        "severity": "warning",
        "description": "Menos del 70% del top-K es reciente",
    },
]


DASHBOARD_REFERENCES: Dict[str, Any] = {
    "overview": {
        "path": "observability/dashboards/pipeline_overview.json",
        "panels": [
            "ingest_rate",
            "dedupe_rate",
            "topk_freshness",
            "error_classes",
        ],
    }
}
