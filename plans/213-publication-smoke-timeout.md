# Plan 213 — El smoke de publicación excede su límite de 15 minutos

## Origen

Durante el PR #432 (plan 212) el job `Validate generated post against front-end
schema` del workflow `Publication Smoke Test` se canceló a los 15 minutos. Una
corrida manual sobre `main` (workflow_dispatch, 2026-11-09 17:36–17:52 UTC) se
canceló igual, así que no depende de ese PR. Su última corrida en verde es del
2026-10-29. Como el workflow solo corre en PRs que tocan `logic/workflows/**` y
otras rutas de publicación, la regresión pasó inadvertida y hoy bloquea cualquier
PR que toque esas rutas.

La reproducción local mostró que el editor sintético termina rápido y que, tras
él, el smoke ejecuta los comandos del frontend (`npm run lint`, `validate:content`,
`build`, `test:dist`, `test:audit`).

**Causa no establecida.** Tres corridas consecutivas (PR #432 a las 17:13 y 17:37,
`main` a las 17:36 UTC) llegaron al límite de 15 minutos, pero la corrida de la
rama de este plan (18:33 UTC) terminó en `success` en 9 min 24 s. La duración no
es, por tanto, una constante por encima de 15 minutos: o varía mucho entre
corridas (red, caché de npm, carga del runner) o hubo una detención puntual que
no se identificó. El log de CI no muestra el tiempo por paso, así que no se puede
atribuir.

## Objetivo

Que el smoke vuelva a ser ejecutable sin enmascarar una lentitud mayor.

Criterios de aceptación:

- `timeout-minutes` del job pasa de 15 a 30.
- El propio archivo del workflow se añade a `on.pull_request.paths`, para que un
  cambio en él se pruebe en su PR en lugar de pasar sin ejecutarse.
- Una corrida del workflow sobre la rama del cambio termina en `success` dentro
  del nuevo límite. **Cumplido:** `success` en 9 min 24 s (2026-11-09).

## Decisiones

- **Subir el límite es margen, no diagnóstico.** Da holgura ante la variación
  observada (9 a más de 15 minutos) sin afirmar que esa sea la causa. Además, el smoke valida el
  esquema de un artículo generado y no necesita `build`, `test:dist` ni
  `test:audit` completos. Acotar lo que valida cambia su contrato y queda como
  seguimiento (opción 2), tras medir cuánto tarda cada paso.
- **No se toca el frontend ni se ejecuta `npm run build` localmente:** el build
  del frontend sube derivados de imagen a R2.

## Verificación

| Comprobación | Comando | Resultado esperado |
|---|---|---|
| Ledger válido | `make plans-ledger-check` | sin errores |
| Smoke dentro del nuevo límite | `gh workflow run publication-smoke.yml --ref fix/publication-smoke-timeout` | `success` en < 30 min |

## Seguimiento

- Medir la duración por paso del smoke (el log actual no la muestra) para
  identificar de dónde sale la variación; si vuelve a agotar 30 minutos, tratarlo
  como detención y no como lentitud.
- Valorar acotar el smoke a validación de esquema.
