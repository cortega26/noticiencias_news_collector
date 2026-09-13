# Troubleshooting FAQ

## SQLite: database is locked

Confirmar la ruta efectiva en la configuración y el proceso que mantiene la
base abierta. Detener el escritor pertinente de forma ordenada; no usar un
`pkill` global ni borrar la base. Revisar transacciones y ejecuciones activas
antes de aumentar concurrencia. SQLite sigue siendo la base seleccionada;
ver [database_deployment.md](database_deployment.md).

## Respuestas HTTP 429

Identificar la fuente y sus respuestas/reintentos en los registros. Revisar
`[rate_limiting]` y la configuración de esa fuente en `config/`. Mantener el
backoff y las restricciones del proveedor. Una ejecución focalizada puede
comprobar conectividad; no demuestra que el backlog se haya procesado.

## Error al guardar configuración

Ejecutar `make config-validate` y revisar la clave indicada por el validador.
`noticiencias/config_manager.py` y `docs/config_fields.md` definen los tipos
y valores admitidos. La raíz `.env` y el entorno pueden sobrescribir
`config.toml`; consultar `--explain <clave>` del módulo de configuración para
conocer la procedencia sin asumir que el archivo gana siempre.

## Modelo o token distinto al esperado

Revisar la procedencia del valor con
`.venv/bin/python -m noticiencias.config_manager --explain ollama.model`.
`apps/refinery/.env` ya no es una fuente de configuración. Reiniciar el
proceso pertinente después de cambiar su configuración de arranque. Un
modelo listado en Ollama no garantiza que haya RAM suficiente para generarlo.

## Módulo o modelo local ausente

Usar `make bootstrap` para el backend y el entorno correspondiente para la
UI heredada. Verificar qué dependencia/modelo requiere el componente y su
configuración; bootstrap no prueba que todos los modelos externos estén
instalados o que los proveedores sean accesibles.

El inicio actual de la GUI es `make admin`. `make refinery` es la alternativa
Streamlit heredada. Ver [RUNBOOK_LOCAL_DEV.md](RUNBOOK_LOCAL_DEV.md) para
puertos, autenticación y límites de dry-run; [runbook.md](runbook.md) para
incidentes y recuperación.
