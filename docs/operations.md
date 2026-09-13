# Operaciones y métricas

Estado: Activo. Revisión documental: 2026-09-04.

Las mediciones de fixtures, los replays y las métricas de producción responden
a preguntas diferentes. Este documento no certifica SLOs de producción ni
la existencia de un dashboard desplegado.

| Pregunta | Fuente comprobable | Límite de la evidencia |
| --- | --- | --- |
| ¿La base responde, hay backlog o ingesta reciente? | `scripts/healthcheck.py` | No demuestra disponibilidad pública ni publicación |
| ¿Qué ocurrió con una ejecución? | `workflow_runs`, workflows de colección/publicación y sus registros | Estado durable no equivale a reanudación de cada paso |
| ¿Cambió el rendimiento de las consultas? | `tests/perf/test_serving_api_perf.py` | Dataset y entorno de prueba; no capacidad de producción |
| ¿Qué estrategia de enriquecimiento se utilizó? | `news_collector/observability/enrichment_metrics_store.py` | Confirmar cobertura, retención y entorno antes de agregar |
| ¿Qué se desplegó? | CI del frontend, callbacks con IDs y comprobación de URLs | Un PR creado o un workflow terminado no bastan |

Los anteriores números de throughput y precisión de fixtures, y el perfil
PostgreSQL simulado, eran capturas históricas. No describen el estado actual:
SQLite es la base seleccionada y varias pruebas antiguas ya no existen en
el árbol activo. Consultar los registros históricos para aquellas capturas,
no usarlas como capacidad prometida.

Para evaluar escalabilidad o rendimiento, registrar revisión, dataset,
entorno, concurrencia, dependencias externas, errores y percentiles junto
con el resultado. Definir un SLO operativo requiere una población, ventana,
fuente de medición y responsable explícitos. Mantener las muestras y los
umbrales junto al código o configuración que realmente los consume.

Ver [performance_baselines.md](performance_baselines.md) para la limitación
del target `make perf`, [runbook.md](runbook.md) para incidentes y
[runbooks/healthcheck.md](runbooks/healthcheck.md) para los checks operativos.
