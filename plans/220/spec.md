# Plan 220 · Recuperar intentos de publicación anteriores al identificador

**Base** `ffebfc9b3c8ff91cd001b3e2cc1c085ab6acbfc6` · 2026-11-23 · **Prioridad** P1 · **Riesgo** alto · **Esfuerzo** M · **Hallazgo** C05

## Resultado

Un intento histórico que ya tiene rama y artefacto adquiere una identidad duradera antes de recuperar su PR. Después de una interrupción, el siguiente pase puede seguir el mismo intento y vincular el PR existente. El callback puede resolver esa identidad con las comprobaciones vigentes.

## Evidencia y alcance

- En `news_collector/logic/workflows/pr_orchestrator.py:195–228`, la recuperación genera en memoria un identificador si faltaba. En `:298–337` puede devolver el URL del PR con ese identificador todavía ausente de la base. `news_collector/storage/database.py:367–442` persiste la proyección antigua y busca después una fila `PUBLISHING` que coincida con el identificador. `news_collector/storage/article_repository.py:712–736` excluye de otro pase una publicación ya proyectada y `news_collector/storage/lifecycle_repository.py:272–281` usa el identificador persistido para resolver el callback.
- En una SQLite aislada con Git simulado, la recuperación devolvió un URL, dejó el intento en `PUBLISHING` y el callback respondió `attempt_not_found`. El artículo dejó de aparecer como candidato de recuperación. Se revisaron las dos entradas de recuperación en `news_collector/logic/workflows/refinery_engine.py`.
- El cambio abarca el orquestador, las dos entradas de Refinery, los métodos de almacenamiento para la recuperación y `news_collector/components/publishing/github_publisher.py`. El adaptador ya busca por rama en `ensure_pull_request_draft` y tras un 422 en `create_pull_request`. Documentar el contrato en `docs/PIPELINE_CONTRACTS.md`. El plan 217 cubre la entrega de evidencia posterior al merge. Coordinar la integración si coinciden cambios de ciclo de vida.

## Decisiones y verificación

1. Antes de interactuar con GitHub, adoptar el intento con una operación transaccional exclusiva de la recuperación. Confirmar que el artículo conserva su rama y estado previos al PR y que el intento sigue siendo el vigente. Reclamar una única fila histórica `PUBLISHING` sin identificador. Crear una fila solo si el estado histórico del artículo respalda la recuperación y no existe otro intento persistido. Ante ambigüedad o una versión concurrente, detenerse. Escribir el mismo identificador en los detalles del intento y en los metadatos del artículo. Mantener la vinculación con la rama y el hash calculado del artefacto.
2. Reutilizar la consulta de PR por rama en GitHub y comprobar repositorio, rama base y vínculo con el artefacto. Reutilizar el resultado verificable o crear un borrador si la consulta confirma la ausencia de un PR asociado. Detenerse si el resultado es ambiguo o GitHub no permite comprobarlo. Mantener el requisito de revisión renovada si el contenido cambió en un PR listo para revisión. Finalizar mediante una sola transacción que compruebe el intento vigente y vincule el PR y el hash, actualice la proyección y registre la transición a `PR_CREATED` y su evento. Si la creación queda incierta o falla la escritura posterior, devolver un estado recuperable con la evidencia disponible. En ambos puntos de entrada, un intento adoptado pendiente de confirmar conserva la recuperación incluso al vencer el plazo previo al reprocesamiento.
3. Probar con SQLite aislada y GitHub simulado. Cubrir la recuperación histórica con callback aceptado, la interrupción entre el PR y la escritura local, el reintento después del plazo con un solo PR y un solo evento, el conflicto con otro intento y una consulta ambigua. Mantener los tests de compatibilidad de la escritura antigua y del flujo identificado.

Criterio de aceptación para los comandos declarados. Todos deben salir con código 0 y ejecutar los casos nuevos.

```bash
.venv/bin/python -m pytest --no-cov \
  tests/unit/storage/test_lifecycle_dual_write.py \
  tests/unit/logic/workflows/test_pr_orchestrator_identity.py \
  tests/unit/logic/workflows/test_publication_callback_attempt_order.py \
  tests/unit/logic/workflows/test_refinery_engine.py \
  tests/integration/test_publication_callback_contract.py
make docs-check
```

Revisar la deriva de los archivos citados desde `ffebfc9b`. Registrar en el índice los resultados de la recuperación y del reintento con almacenamiento local. La aceptación de un callback simulado acredita el contrato local.

## Evidencia local de implementación

Pasaron 125 casos focalizados y la suite unitaria completa, además de lint, docs-check, contratos, límites del sistema, quality-gate y el control de cobertura. La prueba con SQLite y GitHub simulado abrió un solo borrador, reusó el PR tras un fallo de escritura y el retiro de la copia local, registró un solo evento de creación y aplicó el callback correlacionado. El reintento operativo usa la selección explícita por ID.
