# Plan 209 — Verificación de fuentes incompleta

## Objetivo y alcance

Impedir que un fallo o respuesta incompleta del verificador se convierta silenciosamente en una publicación. El cambio propuesto cubriría la falla de infraestructura de la etapa 7; aún no está implementado y no demostraría que una afirmación incierta esté presentada con cautela ni que exista aportación original. No se propone cambiar el contrato de frontmatter y no equivale a una revisión humana.

## Invariantes

- El verificador mantiene sus resultados `confirmed`, `uncertain` y `disputed`. Una incertidumbre emitida por una verificación completada no se bloquea automáticamente.
- Antes de sellar el borrador, exigir un resultado explícito `verification_status: reviewed` para la lista final no vacía de afirmaciones verificadas; un resultado ausente, fallido o incompleto impide la publicación con un código de error propio y diagnóstico seguro.
- Comprobar el resultado de la última verificación posterior a cualquier reparación; un resultado válido anterior no debe habilitar un cuerpo reparado sin verificar.
- Preservar la lógica existente que bloquea `disputed`, la identidad y las excepciones del ciclo de corrección. No autorizar overrides de frontmatter para eludir esta barrera.
- No afirmar que la comparación con la fuente de entrada constituye corroboración independiente. La distinción entre una incertidumbre expresada correctamente y una afirmación categórica requiere un control adicional y permanece abierta.

## Pruebas y validación

Añadir pruebas de integración de la ruta real de preparación para fallo del proveedor, respuesta parcial, verificación completa con `uncertain`, y reparación seguida de fallo de verificación. Acreditar que ningún borrador sellado resulta de un fallo y que un resultado previo no permite eludir una verificación final fallida. Mantener las pruebas existentes de `disputed` y de excepciones del corrector.

Ejecutar pruebas editoriales dirigidas, `make lint`, `make type`, `make test` y `make quality-gate`. Como se modifica una cadena LLM, `make llm-canary ARGS="--require-keys"` y evidencia de una ejecución real aislada son necesarias antes de declarar resuelta la operación. No modificar datos exportados del usuario ni lanzar una publicación real.

## Hallazgos de revisión independiente — diseño adicional obligatorio

- Un checkpoint editorial sellado puede reanudarse sin volver a ejecutar `prepare_article`. El sello acredita integridad, no un control de fuentes satisfactorio. Se requiere evidencia versionada vinculada al borrador final o revalidación explícita antes de ensamblar, con compatibilidad segura para checkpoints anteriores y sin destruir el trabajo guardado.
- El frontmatter de entrada puede reemplazar `fact_check` después de la verificación. La lista visible debe corresponder a la lista verificada, incluso cuando la lista generada está vacía; preservar explícitamente los flujos de correcciones manuales y probar ambos casos.
- La primera barrera experimental en `prepare_article` no cubría estas rutas y fue retirada; el gate aún no está implementado. La resolución requiere pruebas de reanudación, overrides y ruta completa antes de cualquier afirmación de cierre.
