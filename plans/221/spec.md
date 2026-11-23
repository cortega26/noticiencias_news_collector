# Plan 221 · Continuar la importación acotada de reportes

**Base** `ffebfc9b3c8ff91cd001b3e2cc1c085ab6acbfc6` · 2026-11-23 · **Prioridad** P1 · **Riesgo** medio · **Esfuerzo** M · **Hallazgo** C08

## Resultado

El comando que importa reportes desde R2 puede avanzar por lotes y retomar una página con fallos recuperables. Su resumen permite distinguir el fin del listado, el límite del lote y una página que requiere reintento.

## Evidencia y alcance

- `news_collector/logic/workflows/report_reconciliation.py:377–442` comienza cada pase sin cursor. `R2KeyPage` ya transporta `next_cursor`, pero `ReconciliationSummary` y `scripts/reconcile_reader_reports.py:138–179` solo exponen `truncated` y los resultados. Con una lista simulada y un límite inferior al total, repetir el comando vuelve a inspeccionar las mismas primeras claves.
- `news_collector/infrastructure/r2_client.py:234–244` convierte un listado truncado sin token en un final aparente. La ruta que traduce el resultado de persistencia en `report_reconciliation.py` debe distinguir un fallo de escritura del fallo de lectura para poder reintentar la página correcta.
- Cambiar el reconciliador, sus tipos de resumen, el cliente y el CLI existentes. Documentar el uso en `docs/RUNBOOK_LOCAL_DEV.md`. Mantener la idempotencia por UUID, el procesamiento acotado por objetos inspeccionados, incluidos los duplicados, y la simulación sin escrituras.

## Decisiones y verificación

1. Añadir la entrada opcional `--cursor` y los campos JSON `continuation_status` (`complete`, `more`, `retry_page`, `list_error`) y `resume_cursor`. El token se conserva opaco y se reanuda con el mismo bucket, prefijo y filtro `--since`. `retry_page` con token nulo indica volver a empezar sin cursor. Conservar `truncated`, los contadores previos y los códigos de salida. Las automatizaciones pueden usar el nuevo estado para distinguir un pase parcial de un listado completo.
2. Avanzar al cursor de la siguiente página cuando todas las claves de la actual tengan un resultado terminal. Los registros importados, duplicados, fuera de fecha, inválidos o confirmados ausentes permiten avanzar. Completar la página acotada ante un fallo de transporte o persistencia y devolver su cursor de entrada para reintentar. Corregir la clasificación de `db_failed` a `persist_failed`. El UUID permite volver a revisar los éxitos de esa página. Una respuesta con más claves que las solicitadas se rechaza antes de procesar la página para evitar omisiones. Tratar un cursor repetido o cíclico y un listado truncado sin token como fallos de listado.
3. Con el CLI y un listado simulado, comprobar dos invocaciones de lote pequeño que avanzan por todas las claves, fin con límite exacto, reintento desde la primera página y desde una posterior, error de lectura, error de escritura y posterior recuperación, duplicados y simulación sin escrituras. Probar páginas sobredimensionadas y respuestas con cursores ausentes o repetidos.

Criterio de aceptación para los comandos declarados. Todos deben salir con código 0 y ejecutar los casos nuevos.

```bash
.venv/bin/python -m pytest --no-cov \
  tests/unit/logic/workflows/test_report_reconciliation.py \
  tests/unit/ops/test_reconcile_reader_reports.py \
  tests/unit/infrastructure/test_r2_client.py
make docs-check
```

Revisar la deriva de los archivos citados desde `ffebfc9b`. Registrar los resultados de los pases con fixtures en el índice. Los tiempos de reanudación y el volumen real de R2 quedan por medir.

## Evidencia local de implementación

Pasaron 88 pruebas focalizadas, 310 de contratos, 3 de límites del sistema y 4.657 unitarias (5 omitidas). También pasaron lint, docs-check, mypy y el control de cobertura. El CLI avanzó entre dos lotes con un R2 simulado y SQLite, y el reconciliador recuperó la misma página tras un fallo de escritura.
