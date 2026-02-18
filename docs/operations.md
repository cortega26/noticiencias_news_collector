# Operaciones, Métricas y SLOs

Este documento describe cómo medimos el desempeño y la confiabilidad del pipeline de Noticiencias, qué fuentes de verdad usar
para cada métrica y cuáles son los objetivos operativos (SLOs) vigentes. Todas las rutas y comandos asumen que trabajas desde la
raíz del repositorio.

## 1. Fuentes de datos

| Métrica | Fuente | Cómo generarla | Artefacto |
| --- | --- | --- | --- |
| Latencia y throughput del pipeline | `pytest tests/perf/test_pipeline_perf.py` | Ejecuta la suite de performance; corre en modo SQLite y PostgreSQL | `reports/perf/pipeline_perf_metrics.json` |
| Latencia de enriquecimiento NLP | `pytest tests/perf/test_enrichment_latency.py` | Usa el dataset dorado de enriquecimiento | `reports/perf/enrichment_latency.json` |
| Throughput de escritura en PostgreSQL | `pytest tests/perf/test_postgres_write_profile.py` | Simula 60 inserciones consecutivas | `reports/perf/postgres_write_profile.json` |
| Disponibilidad por fuente | `python scripts/replay_outage.py tests/data/monitoring/outage_replay.json` | Reproduce el log operacional semanal | `reports/ops/monitoring_outage_report.json` |

Todos los artefactos se actualizan automáticamente cuando corres las pruebas/perfiles anteriores.

## 2. Procedimiento de recolección

1. Ejecuta la suite de performance completa:
   ```bash
   pytest tests/perf/test_pipeline_perf.py tests/perf/test_postgres_write_profile.py tests/perf/test_enrichment_latency.py
   ```
   Esto genera o actualiza los tres reportes dentro de `reports/perf/`.
2. Si necesitas refrescar los indicadores operacionales, vuelve a procesar el payload semanal:
   ```bash
   mkdir -p reports/ops
   python scripts/replay_outage.py tests/data/monitoring/outage_replay.json > reports/ops/monitoring_outage_report.json
   ```
3. Calcula el ratio de disponibilidad global (normalizando ratios > 1 a 1.0) con:
   ```bash
   python - <<'PY'
   import json
   from pathlib import Path

   report = json.loads(Path("reports/ops/monitoring_outage_report.json").read_text())
   ratios = [min(metric["value"], 1.0) for metric in report["metrics"] if metric["name"] == "source.ingestion_ratio"]
   availability = sum(ratios) / len(ratios) if ratios else 0.0
   print(f"availability_ratio={availability:.2%}")
   PY
   ```

## 3. Métricas validadas (última captura)

- **Pipeline (SQLite dev profile)**: 11.5 artículos/s end-to-end, con p95 de ingestión en 128 ms y enriquecimiento p95 en 72 ms.
- **Pipeline (perfil PostgreSQL simulado)**: 46.6 artículos/s end-to-end con p95 de ingestión en 31.7 ms. Configuración de pool `QueuePool(12/6)`.
- **Accuracy del scorer**: error absoluto medio 0.0, 100% de acierto en `should_include` y ordenamiento igual al dorado.
- **Enriquecimiento NLP**: p95 en 0.39 ms (muy por debajo del presupuesto de 250 ms).
- **Disponibilidad observada**: 50% de ratio de ingesta (1 de 2 fuentes dentro de objetivo) en el replay semanal, con 2 fuentes suprimidas.

Consulta los valores exactos en los reportes JSON vinculados en la tabla de la sección 1 para un análisis detallado.

## 4. Objetivos de nivel de servicio (SLOs)

| Dominio | SLO | Umbral | Fuente |
| --- | --- | --- | --- |
| Latencia de ingestión | p95 ≤ 0.35 s, p99 ≤ 0.45 s | `PIPELINE_PERF_THRESHOLDS['ingestion']` | `reports/perf/pipeline_perf_metrics.json` |
| Latencia de enriquecimiento | p95 ≤ 0.25 s | `PIPELINE_PERF_THRESHOLDS['enrichment_nlp']` | `reports/perf/enrichment_latency.json` |
| Precisión de scoring | `mean_absolute_error` ≤ 0.02, `should_include_accuracy` ≥ 0.95 | Métricas derivadas del dorado | `reports/perf/pipeline_perf_metrics.json` |
| Disponibilidad de fuentes | Ratio de ingesta normalizado ≥ 0.90 para cada fuente; media semanal ≥ 0.95 | Replay semanal y dashboards | `reports/ops/monitoring_outage_report.json` |

Cuando una métrica cae por debajo del objetivo, crea un incidente en el canal de operaciones y adjunta el JSON correspondiente. La
historia y evolución de los objetivos debe registrarse en los `CHANGELOG.md` operativos.

## 5. Automatización y próximos pasos

- Publicar los reportes de `reports/perf/` como artefactos en CI para tener un historial semanal.
- Enriquecer el replay operacional con métricas de latencia de alerta y disponibilidad de API (no solo ingesta).
- Integrar un job nocturno que ejecute el cálculo de disponibilidad y alimente el dashboard de Grafana.
