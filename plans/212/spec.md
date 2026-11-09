# Plan 212 — Compuerta de evidencia antes de abrir el PR

## Origen

Revisión editorial de los PRs de contenido #402, #398, #406, #391, #407 y #408 del
frontend (2026-11-08 y 2026-11-09). Seis de seis llegaron con afirmaciones que la
fuente ingerida no respalda. El plan 211 cubrió `sources`, `fact_check`, estructura
del cuerpo y voz, pero el **cuerpo** seguía sin compuerta: la comprobación de
`editorial/grounding.py` es consultiva (sus hallazgos solo llegan al cuerpo del PR) y
no mira nombres, siglas ni términos técnicos.

| Defecto observado | PR | Detectado antes |
|---|---|---|
| `harmalina`, `DMT`, `LC-MS/MS`, `IMAO`, una cita sobre DMT y «5.000 metros» ausentes de la fuente | #407 | No (cifra solo como aviso) |
| `50` localidades, `200 000` ejemplares, `160`/`88` millones de años, «cientos de miles» | #408 | Solo como aviso |
| `APOE`, `TREM2`, `LPS` ausentes de la fuente | #402 | No |
| Cifra `48` y siglas sin respaldo | #391 | Solo como aviso |
| Detalle de métodos añadido a un resumen de preprint | #398 | No |
| Afirmaciones sin término distintivo (comparativas o de conocimiento general) | #407, #408 | No |

## Objetivo

Convertir en bloqueo, **antes de crear rama, commit o PR**, la parte del problema que
es detectable de forma determinista: especificidades comprobables (cifras,
cuantificadores vagos, siglas y códigos, DOI) que el borrador contiene y la evidencia
ingerida no. Sin red, sin LLM, sin cambios de contrato.

## Diseño (fase 1)

Módulo puro `news_collector/editorial/evidence_gate.py` y cableado en
`RefineryEngine._enforce_publication_gates`, el único punto por el que pasan el
borrador nuevo **y** el reanudado desde checkpoint (la ruta reanudada no vuelve a
ejecutar el editor ni `prepare_article`).

- `evaluate_evidence_gate(markdown, source_text) -> EvidenceGateDecision`.
- Cifras y cuantificadores: se reutilizan los hallazgos `ERROR` de `check_grounding`
  (`number`, `vague_quantifier`). Siglas: `[A-Z]…` con ≥2 mayúsculas o dígitos, sin
  respaldo en la fuente. DOI del cuerpo que no está en la fuente.
- Se bloquea con `>= 2` especificidades **distintas** sin respaldo
  (`editorial_unsupported_specifics`). Una sola es ruido tolerable.
- **Fuente corta (< 1500 caracteres) falla cerrada**: umbral `1`. La evidencia
  delgada es de donde salieron las invenciones; el chequeo consultivo la omitía.
- Falsos positivos evitados: equivalentes español/inglés (`ADN`↔`DNA`, `IMAO`↔`MAOI`,
  `LCR`↔`CSF`…), números romanos, `IA`/`EE. UU.`, y siglas que el propio artículo
  define (`fecundación in vitro (FIV)`, con iniciales verificadas).
- **Falla cerrada ante defecto del chequeador** (a diferencia de la etapa consultiva,
  que lo ignora): bloquea con `reason: checker_error`.
- Al bloquear: etapa `evidence_gate` fallida con los hallazgos, `persist_attempt(False)`,
  `_last_blocked_error` con el código; el panel de administración lo muestra y no se
  abre PR. La etapa consultiva `grounding` sigue igual.

## Calibración (contenido real, `data/news_v3.db` + PRs del frontend)

Original del publicador vs. versión corregida en `main`, con la `content` real que
vio el editor:

| PR | Original | Corregido |
|---|---|---|
| #402 | BLOQUEA (`LPS`, `APOE`, `TREM2`) | pasa (1) |
| #398 | pasa | pasa |
| #406 | pasa | pasa (1) |
| #391 | BLOQUEA (cifra `48` + siglas) | pasa (1) |
| #407 | BLOQUEA (`DMT`, `IMAO`, `LC-MS/MS`, `5.000`) | pasa (1) |
| #408 | BLOQUEA (8 especificidades) | **bloquea** (13) |

Detecta 4 de 6 originales sin falsos positivos en las corregidas. #408 corregido
también se bloquea **a propósito**: sus cifras (1 919 muestras, 55 478 OTU…) vienen
del PDF completo, que la `content` ingerida no incluye; el pipeline no puede
verificarlas con su evidencia. La salida es enriquecer la evidencia (fase 3), no
relajar la compuerta.

## Lo que esta fase NO cubre (declarado)

- Afirmaciones sin término distintivo: «duplica o triplica los catálogos», «no hay
  pequeños mamíferos», «casi idéntica». Son comparativas o de conocimiento del mundo.
- Nombres de persona equivocados, fechas/años mal asignados, y un error aislado
  (una sola sigla o cifra) por debajo del umbral. #398 y #406 originales pasan.
- Que la forma larga de una sigla definida en el texto sea cierta.

Esas clases requieren verificación a nivel de afirmación (plan 209 y fase 2).

## Fases posteriores (no implementadas)

2. **Resolver antes de bloquear.** Alimentar los hallazgos al editor para una
   reescritura acotada («elimina o respalda esto») reutilizando el patrón de
   reintento de `run_critic_gate`, volver a evaluar y bloquear solo si persisten.
   Cambia la cadena LLM: exige `make llm-canary ARGS="--require-keys"`.
3. **Evidencia suficiente.** Para preprints (bioRxiv), recuperar el texto completo
   (PDF/HTML) en la ingesta cuando solo hay resumen, y registrar la completitud de la
   evidencia por artículo.
4. **Verificación de afirmaciones del cuerpo** (con el plan 209).

## Pruebas y validación

`tests/unit/editorial/test_evidence_gate.py` (reglas), `tests/unit/logic/workflows/
test_evidence_gate_wiring.py` (motor: ruta nueva, ruta reanudada, falla cerrada) y el
ajuste de `test_grounding_stage_is_advisory_and_persists_findings` (la fuente corta
ya no publica). `make lint`, `make type`, `make test`, `make quality-gate`. Sin LLM:
no requiere `llm-canary` en la fase 1.

## Riesgo operativo

Bloquea más artículos de fuentes delgadas. Es deseado, pero conviene vigilar la tasa
de `editorial_unsupported_specifics` en el panel tras el despliegue; los umbrales y
equivalentes viven como constantes del módulo y se ajustan con otro PR.
