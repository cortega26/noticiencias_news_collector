"""Gestor centralizado de observabilidad (logs estructurados, métricas y trazas)."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from loguru import logger
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.trace import Status, StatusCode

from config.observability import OBSERVABILITY_CONFIG, SLO_DEFINITIONS


class ObservabilityManager:
    """Coordina logging estructurado, métricas y trazas para el pipeline."""

    def __init__(self) -> None:
        self._initialized = False
        self._tracer = None
        self.registry: Optional[CollectorRegistry] = None
        self.stage_latency: Optional[Histogram] = None
        self.visibility_latency: Optional[Histogram] = None
        self.ingest_sources: Optional[Counter] = None
        self.ingest_articles: Optional[Counter] = None
        self.pipeline_errors: Optional[Counter] = None
        self.dedupe_outcomes: Optional[Counter] = None
        self.queue_lag_seconds: Optional[Gauge] = None
        self.topk_freshness_ratio: Optional[Gauge] = None
        self.active_traces: Optional[Gauge] = None
        self.slo_config = SLO_DEFINITIONS

    def initialize(
        self, service_name: Optional[str] = None, environment: Optional[str] = None
    ) -> None:
        """Inicializa tracer y métricas si aún no se ha hecho."""

        if self._initialized:
            return

        service_name = service_name or OBSERVABILITY_CONFIG["service_name"]
        environment = environment or OBSERVABILITY_CONFIG.get("environment", "local")

        resource = Resource.create(
            {
                "service.name": service_name,
                "service.namespace": OBSERVABILITY_CONFIG.get(
                    "service_namespace", "news"
                ),
                "service.environment": environment,
            }
        )

        tracer_provider = TracerProvider(resource=resource)
        tracer_provider.add_span_processor(
            SimpleSpanProcessor(ConsoleSpanExporter())
        )
        trace.set_tracer_provider(tracer_provider)
        self._tracer = trace.get_tracer(service_name)

        self.registry = CollectorRegistry()

        buckets = OBSERVABILITY_CONFIG["metrics"][
            "stage_latency_buckets_seconds"
        ]
        visibility_buckets = OBSERVABILITY_CONFIG["metrics"][
            "visibility_latency_buckets_seconds"
        ]

        self.stage_latency = Histogram(
            "news_pipeline_stage_latency_seconds",
            "Tiempo empleado por etapa del pipeline",
            labelnames=["stage"],
            buckets=buckets,
            registry=self.registry,
        )
        self.visibility_latency = Histogram(
            "news_pipeline_visibility_latency_seconds",
            "Tiempo de ingestión a visibilidad",
            buckets=visibility_buckets,
            registry=self.registry,
        )
        self.ingest_sources = Counter(
            "news_ingest_sources_total",
            "Fuentes procesadas por resultado",
            labelnames=["source_id", "outcome"],
            registry=self.registry,
        )
        self.ingest_articles = Counter(
            "news_ingest_articles_total",
            "Artículos detectados y guardados por fuente",
            labelnames=["source_id", "status"],
            registry=self.registry,
        )
        self.pipeline_errors = Counter(
            "news_pipeline_errors_total",
            "Errores por etapa y clase",
            labelnames=["stage", "error_type"],
            registry=self.registry,
        )
        self.dedupe_outcomes = Counter(
            "news_dedupe_outcomes_total",
            "Resultados del proceso de deduplicación",
            labelnames=["outcome"],
            registry=self.registry,
        )
        self.queue_lag_seconds = Gauge(
            "news_pipeline_queue_lag_seconds",
            "Retraso de colas/etapas del pipeline",
            labelnames=["stage"],
            registry=self.registry,
        )
        self.topk_freshness_ratio = Gauge(
            "news_pipeline_topk_freshness_ratio",
            "Proporción de artículos frescos (<12h) en el top-K",
            registry=self.registry,
        )
        self.active_traces = Gauge(
            "news_pipeline_active_traces",
            "Número de trazas activas del ciclo de pipeline",
            registry=self.registry,
        )

        self._initialized = True
        self.log_event(
            stage="observability",
            event="initialized",
            service_name=service_name,
            environment=environment,
        )

    @property
    def tracer(self):
        if not self._tracer:
            raise RuntimeError("ObservabilityManager.initialize debe ejecutarse primero")
        return self._tracer

    def log_event(self, stage: str, event: str, **fields: Any) -> None:
        """Emite un log estructurado con contexto consistente."""

        payload = {"stage": stage, "event": event, **fields}
        logger.bind(**payload).info(event)

    def record_ingestion_result(
        self, source_id: str, result: Dict[str, Any], trace_id: Optional[str] = None
    ) -> None:
        """Actualiza métricas de ingestión por fuente."""

        if not self._initialized or not self.ingest_sources or not self.ingest_articles:
            return

        outcome = "success" if result.get("success") else "error"
        self.ingest_sources.labels(source_id=source_id, outcome=outcome).inc()
        self.ingest_articles.labels(source_id=source_id, status="found").inc(
            result.get("articles_found", 0)
        )
        self.ingest_articles.labels(source_id=source_id, status="saved").inc(
            result.get("articles_saved", 0)
        )
        if not result.get("success"):
            error_type = result.get("error_message", "unknown_error")
            self.record_error("ingestion", error_type)
        self.log_event(
            stage="ingestion",
            event="source_processed",
            source_id=source_id,
            outcome=outcome,
            trace_id=trace_id,
            articles_found=result.get("articles_found", 0),
            articles_saved=result.get("articles_saved", 0),
            latency_ms=int(result.get("processing_time", 0) * 1000),
            collector=result.get("collector"),
        )

    def record_dedupe_result(
        self,
        outcome: str,
        article_id: Optional[int] = None,
        cluster_id: Optional[str] = None,
        confidence: Optional[float] = None,
    ) -> None:
        if not self._initialized or not self.dedupe_outcomes:
            return

        self.dedupe_outcomes.labels(outcome=outcome).inc()
        self.log_event(
            stage="dedupe",
            event="dedupe_outcome",
            outcome=outcome,
            article_id=article_id,
            cluster_id=cluster_id,
            confidence=confidence,
        )

    def record_error(self, stage: str, error_type: str) -> None:
        if not self._initialized or not self.pipeline_errors:
            return
        normalized = error_type.replace(" ", "_").lower()
        self.pipeline_errors.labels(stage=stage, error_type=normalized).inc()
        self.log_event(stage=stage, event="error", error_type=normalized)

    def update_queue_lag(self, stage: str, lag_seconds: float) -> None:
        if not self._initialized or not self.queue_lag_seconds:
            return
        self.queue_lag_seconds.labels(stage=stage).set(lag_seconds)

    def record_topk_freshness(self, ratio: float) -> None:
        if not self._initialized or not self.topk_freshness_ratio:
            return
        self.topk_freshness_ratio.set(max(0.0, min(1.0, ratio)))
        self.log_event(
            stage="ranking",
            event="freshness_ratio_updated",
            freshness_ratio=ratio,
        )

    def observe_visibility_latency(self, latency_seconds: float) -> None:
        if not self._initialized or not self.visibility_latency:
            return
        self.visibility_latency.observe(latency_seconds)
        self.log_event(
            stage="pipeline",
            event="visibility_latency",
            latency_seconds=latency_seconds,
        )

    @contextmanager
    def start_trace(self, name: str, **attributes: Any):
        if not self._initialized:
            raise RuntimeError("ObservabilityManager.initialize debe ejecutarse primero")
        if self.active_traces:
            self.active_traces.inc()
        with self.tracer.start_as_current_span(name, attributes=attributes) as span:
            try:
                yield span
            finally:
                if self.active_traces:
                    self.active_traces.dec()

    @contextmanager
    def instrument_stage(self, stage_name: str, **attributes: Any):
        if not self._initialized:
            raise RuntimeError("ObservabilityManager.initialize debe ejecutarse primero")

        start_time = time.time()
        with self.tracer.start_as_current_span(stage_name, attributes=attributes) as span:
            self.log_event(stage_name, "stage.start", **attributes)
            try:
                yield span
                outcome = "success"
            except Exception as exc:  # pragma: no cover - defensive logging
                outcome = "error"
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                self.record_error(stage_name, type(exc).__name__)
                raise
            finally:
                elapsed = time.time() - start_time
                if self.stage_latency:
                    self.stage_latency.labels(stage=stage_name).observe(elapsed)
                self.log_event(
                    stage_name,
                    "stage.end",
                    duration_ms=int(elapsed * 1000),
                    outcome=outcome,
                    **attributes,
                )

    def evaluate_slos(
        self,
        ingest_visible_minutes: float,
        error_rate: float,
        freshness_ratio: float,
        dedupe_effectiveness: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Evalúa cada SLO y devuelve su estado actual."""

        results: List[Dict[str, Any]] = []
        dedupe_effectiveness = (
            dedupe_effectiveness
            if dedupe_effectiveness is not None
            else self._estimate_dedupe_effectiveness()
        )

        checks = {
            "ingest_to_visible_minutes": ingest_visible_minutes,
            "pipeline_error_rate": error_rate,
            "topk_freshness_ratio": freshness_ratio,
            "dedupe_effectiveness": dedupe_effectiveness,
        }

        for slo_name, value in checks.items():
            slo_def = self.slo_config.get(slo_name)
            if slo_def is None or value is None:
                continue

            status = "ok"
            if slo_name == "topk_freshness_ratio" or slo_name == "dedupe_effectiveness":
                if value < slo_def["critical"]:
                    status = "critical"
                elif value < slo_def["warning"]:
                    status = "warning"
            else:
                if value > slo_def["critical"]:
                    status = "critical"
                elif value > slo_def["warning"]:
                    status = "warning"

            result = {
                "slo": slo_name,
                "value": value,
                "status": status,
                "target": slo_def["target"],
                "warning": slo_def["warning"],
                "critical": slo_def["critical"],
                "description": slo_def.get("description"),
            }
            results.append(result)
            self.log_event("slo", "evaluation", **result)

        return results

    def _estimate_dedupe_effectiveness(self) -> Optional[float]:
        if not self._initialized or not self.dedupe_outcomes:
            return None

        metric = self.dedupe_outcomes.collect()
        total = 0.0
        duplicates = 0.0
        for family in metric:
            for sample in family.samples:
                total += sample.value
                if sample.labels.get("outcome") != "new":
                    duplicates += sample.value
        if total == 0:
            return None
        return duplicates / total

    def export_metrics_snapshot(self) -> Dict[str, Any]:
        if not self.registry:
            return {}
        snapshot: Dict[str, Any] = {}
        for metric in self.registry.collect():
            samples: List[Dict[str, Any]] = []
            for sample in metric.samples:
                samples.append(
                    {
                        "name": sample.name,
                        "labels": sample.labels,
                        "value": sample.value,
                    }
                )
            snapshot[metric.name] = samples
        return snapshot

    def export_metrics_json(self) -> str:
        return json.dumps(self.export_metrics_snapshot(), indent=2, ensure_ascii=False)


_observability_instance: Optional[ObservabilityManager] = None


def get_observability() -> ObservabilityManager:
    global _observability_instance
    if _observability_instance is None:
        _observability_instance = ObservabilityManager()
    return _observability_instance
