# Plan 205: estado

- [x] Diagnóstico del bloqueo actual (`_enforce_fact_check_gate`, etapa 7)
- [x] Spec
- [x] Módulo de política `fact_check_correction.py` + tests unitarios
- [ ] `_verify_fact_check_claims` guarda motivos (`last_fact_check_reasons`)
- [x] Hooks del `EditorAgent`: gravedad, corrección, control residual
- [x] Refactor de etapas 5 y 6 en `_derive_publishable` y conexión del bucle
- [x] Caché de la etapa 2 reemplazada tras corregir; checkpoint técnico invalidado
- [x] Trazabilidad en `grounding_notes` y `last_source_support_verdict`
- [x] Prompts nuevos y salida con `reason` en `fact_check_verification`
- [x] Tests de integración en `test_fact_check_verification.py`
- [x] `make test`, `make lint`, `make type` (lint limpio; `make type` y 2 tests de `test_daily_publish.py` ya fallan en `main`, ajenos a este plan; el módulo nuevo pasa mypy)
- [x] Revisión independiente de spec frente a implementación. Corregido: traza
      conservada también en rechazos (A8), aviso explícito si la caché de la
      etapa 2 no se reemplaza (A6), fallos al rederivar → reintentable (A7),
      test de gravedad indeterminada en la última ronda.
- [x] Fase 2: el rechazo definitivo se guarda en la base (`rejected` +
      `editorial_rejection`) y sale de todas las fuentes de candidatos
      (exportación, lista de publicables del admin, cargador del pipeline).
- [ ] PR
