# Plan 206: el verificador lee la fuente completa

**Prioridad:** P1 · **Esfuerzo:** S-M · **Depende de:** 205

## Problema

`_verify_fact_check_claims` (etapa 7) envía al verificador una muestra de la
fuente de 6.000 caracteres (`_sample_for_critic`: inicio, mitad y final). La
mitad de las fuentes recientes supera 5.300 caracteres; el 10 % supera 13.500.
Cuando el dato que se verifica está en un tramo omitido, el verificador no
puede verlo.

Evidencia (artículo 3712, fuente de 11.627 caracteres; la muestra omite el
párrafo "only 14 out of 89"):

| Afirmación | Con muestra | Con fuente completa | Correcto |
| --- | --- | --- | --- |
| "solo 3 de 89 diseños…" (error real) | `uncertain` | `disputed` ("la fuente indica 14 de 89, no 3") | `disputed` |
| "solo 14 de 89 diseños…" | `uncertain` | `confirmed` | `confirmed` |
| "evolución dirigida in silico mejoró…" | `disputed` | `confirmed` (mutaciones identificadas computacionalmente) | `confirmed` |

La muestra produce falsos negativos (un error real pasa) y falsos positivos
(el bloqueo del proceso 96 fue uno). Los pasos del plan 205 (gravedad,
corrección) también reciben muestras de 6.000 y 8.000 caracteres: el corrector
podría "corregir" una cifra con una muestra que no contiene la correcta.

## Objetivos (criterios de aceptación)

- **B1.** El verificador recibe la fuente completa hasta
  `FACT_CHECK_SOURCE_MAX_CHARS = 40_000` (cubre el p99 de las fuentes
  recientes, 32.632). Por encima se muestrea con `_sample_for_critic` y se
  registra una advertencia.
- **B2.** Una sola llamada por artículo verifica todas las afirmaciones (en
  lotes de `FACT_CHECK_CLAIMS_PER_CALL = 12`). Con la fuente completa, una
  llamada por afirmación multiplicaría los tokens por el número de
  afirmaciones contra el límite de Groq (8.000 tokens/minuto).
- **B3.** Las afirmaciones se identifican por id (`c1`, `c2`, …) en el prompt
  y en la respuesta `{"verdicts": [{"id", "status", "reason"}]}`. Un id
  ausente, duplicado o desconocido deja esa afirmación en `uncertain` y
  registra el problema en `issues`. Si el lote tiene una sola afirmación, se
  acepta también la forma plana `{"status", "reason"}`.
- **B4.** Se conservan todas las invariantes de la etapa 7: firma y retorno de
  `_verify_fact_check_claims`; sobrescritura de todos los estados; fallo de
  infraestructura, JSON inválido, prompt ausente o fuente vacía → `uncertain`
  (nunca `disputed`); afirmaciones mal formadas descartadas; etiqueta vacía →
  `uncertain` sin llamada; marca de resumen; motivos en
  `last_fact_check_reasons`; bloques de datos no confiables.
- **B5.** Si la verificación termina sin revisar todo
  (`verification_status = "unverified"`), se registra una advertencia
  visible con el número de afirmaciones afectadas.
- **B6.** Juicio de gravedad, corrección y control residual (plan 205) usan el
  mismo presupuesto de fuente.

## Diseño

- `ai_editor.py`:
  - `FACT_CHECK_SOURCE_MAX_CHARS`, `FACT_CHECK_CLAIMS_PER_CALL`.
  - `_source_for_verification(source) -> str`: completa o muestreada (B1).
  - `_verify_fact_check_claims`: arma lotes, construye un prompt con la lista
    de afirmaciones (JSON con ids) y la fuente, y asigna veredictos por id
    con `_parse_fact_check_verdicts`.
  - `_judge_fact_check_severity` y `_correct_disputed_claims` usan
    `_source_for_verification`.
- `config/prompts.yaml` (`fact_check_verification`): mismas reglas de
  verificación, ahora para varias afirmaciones; formato de salida con
  `verdicts`.
- Que un pedido sea demasiado grande para un proveedor no deja el artículo
  sin verificar: `failure_kinds` clasifica 413 como `CLIENT_ERROR`, que pasa
  al siguiente proveedor de la cadena `fact_check` (groq → gemini →
  cloudflare).

## Verificación

| Qué | Cómo |
| --- | --- |
| Lotes, ids y fallos | Tests unitarios reescritos en `test_fact_check_verification.py`: estados por id, id ausente/duplicado/desconocido, forma plana con una afirmación, lote de 13 afirmaciones en 2 llamadas, fallo de infraestructura, prompt ausente, fuente vacía, resumen, entre idiomas. |
| Fuente completa (regresión) | Test: fuente sintética larga con la frase clave en el tramo que `_sample_for_critic(…, 6000)` omite; la frase llega al prompt. Fuente de más de 40.000 caracteres → muestreo y advertencia. |
| Plan 205 sin cambios de comportamiento | Tests de integración de corrección siguen pasando con el stub adaptado al formato por lotes. |
| Modelos reales | Prueba en seco opcional (`NOTICIENCIAS_FACT_CHECK_LIVE=true`) con fuente propia; manual con el artículo 3712: la tabla de arriba con fuente completa. Tokens medidos con el campo `usage`. |
| Regresión | `make test`, `make lint`. |
