# Plan 217 · Conservar evidencia exacta hasta confirmar el despliegue

**Bases** Collector `ffebfc9b3c8ff91cd001b3e2cc1c085ab6acbfc6` · frontend `e271512f744998e25a1da3175797a25fa6c89f1e` · 2026-11-22

**Prioridad** P1 · **Riesgo** medio · **Esfuerzo** M · **Hallazgos** C03 y C04

## Resultado

Una entrega corregida puede completar su intento exacto, los reintentos de transporte siguen deduplicados y la reconciliación muestra una PR integrada como pendiente hasta disponer de evidencia de despliegue. La opción de rechazar una PR cerrada sin merge conserva su comportamiento.

## Estado y alcance

- En el frontend, `scripts/backend-notify.js:60–69,93–111` identifica una entrega por run y evento. Conserva el mismo ID al reconstruir el envelope con referencias que antes no estaban. En Collector, `storage/webhook_receipt_repository.py:79–97` conserva la fila inicial y `serving/webhook_handler.py:65–88` devuelve su resultado si fue procesado. SQLite temporal confirmó que la segunda entrega se descarta.
- El plan 198 decidió tratar merge como evidencia en `plans/198/spec.md:20–38`. `publication_reconciliation.py:382–424,529–569` puede crear `deployed` con fecha de merge y URL raíz. `docs/PIPELINE_CONTRACTS.md:116–120,279–282` exige despliegue. La prueba `tests/unit/storage/test_publication_reconciliation_github.py:111–131` fija la conducta actual y se reemplazará con la nueva regla.
- Alcance frontend. `scripts/backend-notify.js`, `tests/backend-notify.test.ts` y `docs/webhook-integration.md`. Alcance Collector. `news_collector/logic/workflows/publication_reconciliation.py`, sus tests de reconciliación GitHub, tests de webhook o recibos y `docs/PIPELINE_CONTRACTS.md`. Evitar cambios en versiones históricas de recibos, IDs de artículos, capacidades de publicación y PR legacy. Coordinar cambios que coincidan en el notificador con el plan 024 del frontend.

## Fases y criterios

1. **Identidad de entrega.** Usar una nueva versión de ID que asocie repo, ejecución, tipo de evento y evidencia material estable, incluidas las referencias exactas canonizadas. Ignorar el timestamp mutable del envelope y ordenar las referencias antes de calcular su huella. Elegir límites compatibles con el validador de `delivery_id` y verificar que el webhook acepte la forma nueva. La entrega antigua conserva su clave y los reintentos byte a byte de la nueva se deduplican. Probar que el primer payload sin referencias queda en atención y que el segundo con nueva evidencia cierra solo el intento correlacionado. Validar igual PR con hash distinto, repetición exacta y callback tardío de una publicación anterior en SQLite temporal.
2. **Reconciliación de merge.** Registrar o mostrar evidencia de merge como resultado pendiente sin una transición `deployed` y sin fecha o URL de publicación. Reusar recibos de despliegue con correlación exacta para el cierre. La rama de PR cerrada sin integrar sigue pasando a `REJECTED` para su intento, con los controles de proyección vigentes. Una segunda pasada produce el mismo resultado si la evidencia sigue igual. Actualizar la decisión de plan 198 mediante referencia a esta enmienda y el contrato activo, conservando el histórico.
3. **Liberación coordinada.** Confirmar primero que el receptor probado acepta la versión nueva del ID y que la entrega repetida funciona. Desplegar primero los cambios de identidad que recuperan evidencia. Cambiar la reconciliación de merge después y verificar que las operaciones pueden recuperar una entrega auténtica. Cualquier corrección de estados históricos requiere un trabajo separado con inventario y aprobación.

| Gate | Evidencia de auditoría | Aceptación |
| --- | --- | --- |
| Frontend `npm run test:audit -- tests/backend-notify.test.ts` y `npm run check:contract-sync` | Suite enfocada y paridad local ejecutadas durante la auditoría | Verde, con fixtures viejos y nuevos. |
| Collector `make docs-check && make test-boundaries && make test-contracts` | Declarados. Pasaron fixtures focalizadas de callback, recibos y reconciliación a nivel Python | Verde en las bases integradas. |
| Collector `make lint && make type && make test && make quality-gate` | Declarados | Verde con lockfiles conforme al entorno. |

Si el receptor interpreta la clave nueva de modo incompatible o una operación depende de la promoción merge-only, demostrar primero un mecanismo de recuperación utilizable. Validar con pruebas aisladas, sin enviar eventos o abrir PR de publicación reales. Actualizar la fila 217 con evidencia de cada fase.


## Evidencia local de implementación

Frontend `2da7714dea317d8b908bd8617507137e1b4fcc6f` y Collector `7ed42e008525fd6be66351f6ed8014930015b585` con cambios locales. Pasaron los 23 casos del notificador, los 1.036 tests del frontend, el build, el chequeo de salida y la paridad del contrato. Pasaron 52 casos de callbacks y reconciliación, 4.663 unitarias, 311 de contratos y 3 de límites en Collector. También pasaron mypy, cobertura, lint, docs-check y quality-gate. Una prueba adicional ejecutó el emisor v1 del frontend versionado para comprobar sus recibos. El emisor v2 real y SQLite verificaron corrección de evidencia en el mismo run, hash incorrecto, cierre exacto y entrega repetida.

El resumen conserva el PR integrado como pendiente y evita atribuir a un intento la proyección de un PR o hash distinto. Los cambios del emisor deben llegar primero a producción. Ambas fases se mantienen locales.
