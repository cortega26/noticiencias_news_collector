# Troubleshooting FAQ

Cuando la tubería falla, comienza con estos síntomas comunes antes de escalar al on-call.

## Error: `sqlite3.OperationalError: database is locked`
- **Contexto típico**: ejecuciones paralelas del colector o scripts de replay golpeando la misma base.
- **Diagnóstico rápido**:
  - Ejecuta `lsof | grep data/news.db` para confirmar procesos aún abiertos.
  - Revisa los locks activos con `sqlite3 data/news.db "PRAGMA locking_mode;"`.
- **Resolución**:
  - Finaliza procesos huérfanos (`pkill -f run_collector.py`) y vuelve a correr `python run_collector.py --healthcheck`.
  - Si necesitas concurrencia, cambia a Postgres siguiendo las instrucciones del [Runbook Operacional](runbook.md#operations-runbook).

## Error: `429 Too Many Requests`
- **Contexto típico**: configuraciones agresivas en `config/sources.yaml` o `config/rate_limits.yaml`.
- **Diagnóstico rápido**:
  - Consulta los logs estructurados (`event: rate_limit.backoff`) para identificar la fuente.
  - Ejecuta `python scripts/rate_limit_probe.py --source <id>` para validar la nueva ventana.
- **Resolución**:
  - Incrementa `min_delay_seconds` para la fuente afectada y, si aplica, ajusta `RATE_LIMITING_CONFIG["domain_overrides"]`.
  - Repite la ejecución con `python run_collector.py --dry-run --sources <id>` y verifica que el Runbook no reporte nuevas alertas.

## Error: `ModuleNotFoundError` para modelos de enriquecimiento
- **Contexto típico**: entorno virtual sin dependencias opcionales o modelos locales eliminados.
- **Diagnóstico rápido**:
  - Comprueba dependencias con `pip install --require-hashes -r requirements.lock`.
  - Verifica la caché de modelos (`.cache/noticiencias/models/`) y las rutas esperadas en `config/enrichment.yaml`.
- **Resolución**:
  - Ejecuta `make bootstrap` para reinstalar dependencias y descargar modelos declarados en el `Makefile`.
  - Si necesitas regenerar embeddings, sigue la sección "Enrichment drift" del [Runbook Operacional](runbook.md#2-dedupe-drift).

> ℹ️ Para incidentes más amplios, consulta `docs/runbook.md` y `docs/collector_runbook.md` junto con los logs estructurados mencionados en el README.
