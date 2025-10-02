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
- **Contexto típico**: configuraciones agresivas en `config/sources.py` o sobrescrituras en `[rate_limiting]` dentro de `config.toml`.
- **Diagnóstico rápido**:
  - Consulta los logs estructurados (`event: rate_limit.backoff`) para identificar la fuente.
  - Ejecuta `python -m scripts.load_test --num-sources 1 --concurrency 1` para observar latencias y reintentos con la fuente problemática.
- **Resolución**:
  - Ajusta `domain_overrides` en `[rate_limiting]` (`config.toml`) o los parámetros de la fuente en `config/sources.py`, y reinicia el collector para aplicar los cambios.
  - Repite la ejecución con `python run_collector.py --dry-run --sources <id>` y verifica que el Runbook no reporte nuevas alertas.

## Error: `ModuleNotFoundError` para modelos de enriquecimiento
- **Contexto típico**: entorno virtual sin dependencias opcionales o modelos locales eliminados.
- **Diagnóstico rápido**:
  - Comprueba dependencias con `pip install --require-hashes -r requirements.lock`.
  - Verifica la caché de modelos (`.cache/noticiencias/models/`) y las rutas esperadas bajo `[enrichment.models]` en `config.toml`.
- **Resolución**:
  - Ejecuta `make bootstrap` para reinstalar dependencias y descargar modelos declarados en el `Makefile`.
  - Si necesitas regenerar embeddings, sigue la sección "Enrichment drift" del [Runbook Operacional](runbook.md#2-dedupe-drift).

> ℹ️ Para incidentes más amplios, consulta `docs/runbook.md` y `docs/collector_runbook.md` junto con los logs estructurados mencionados en el README.
