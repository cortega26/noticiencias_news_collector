"""Genera un escenario sintético que dispara las alertas de SLO."""

from __future__ import annotations

import json

from src.utils.observability import get_observability


def run_synthetic_alert_scenario() -> None:
    obs = get_observability()
    obs.initialize()

    # Simular métricas negativas
    obs.observe_visibility_latency(20 * 60)  # 20 minutos
    obs.record_topk_freshness(0.5)
    obs.record_error("ingestion", "timeout")
    obs.record_dedupe_result("duplicate_content")

    slo_results = obs.evaluate_slos(
        ingest_visible_minutes=20,
        error_rate=0.02,
        freshness_ratio=0.5,
        dedupe_effectiveness=0.6,
    )

    snapshot = {
        "slo_results": slo_results,
        "metrics": obs.export_metrics_snapshot(),
    }
    print(json.dumps(snapshot, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    run_synthetic_alert_scenario()
