# Plan 211 — Integridad de fuentes y afirmaciones antes de sellar el borrador

## Origen

Revisión editorial de los PRs de contenido #406, #402, #398 y #391 del frontend
(2026-11-08). Todos llegaron como borradores con defectos que ninguna compuerta
del pipeline detectó:

| Defecto observado | PR | Compuerta que faltaba |
|---|---|---|
| DOI y título de paper inventados (404), fecha de fuente de 2024 en una nota de 2026, "fuente" que era la portada de una universidad | #406 | `sources` no se contrasta con la evidencia ingerida |
| Afirmaciones del equipo, disputadas por una experta, marcadas `confirmed` ("más antigua y sólida", "explica el sesgo sexual") | #406, #402 | `fact_check` confirma lenguaje categórico aun con nota de incertidumbre |
| Cuerpo con métodos, contexto y detalles que la fuente ingerida (solo resumen y autores) no contiene | #402, #398 | Parcial: `grounding.py` (consultivo) cubre cifras y alcance; un endurecimiento del prompt se probó y se descartó (ver «Prompt de enriquecimiento») |
| Línea de titular suelta al inicio del cuerpo | #398, #391 | Sin compuerta de estructura del cuerpo |
| `#etiqueta` en el cuerpo (rompe una prueba del frontend) | #391 | Solo se detectaba en el frontend |
| Nombre de persona distinto entre frontmatter y cuerpo (Valeriy/Pavlo) | #391 | Sin consistencia frontmatter-cuerpo |
| Voz en segunda persona ("tus huesos", "¿Te has preguntado…") | #398 | Sin compuerta de voz |

## Objetivos

Prevenir o minimizar esos defectos con reglas deterministas, sin red y sin
modificar el contrato de frontmatter. No sustituyen la revisión humana ni la
verificación de fuentes del plan 209 (siguen abiertos).

## Diseño

Módulo puro nuevo `news_collector/editorial/source_integrity.py` (sin I/O, LAW de
módulos de política) y cableado en `prepare_editorial_draft`
(`components/editorial/editorial_publication_artifact.py`).

1. **`ground_sources`** — una fuente generada solo se conserva si su URL es la
   `source_url` del artículo, aparece literalmente en la evidencia ingerida, o su
   DOI aparece en ella. Se descartan URLs de portada (sin ruta). Si no sobrevive ninguna,
   se añade la fuente primaria (`source_url`) con el título y el editor conocidos,
   para que `sources` nunca quede vacío por esta regla. La
   fecha de una fuente solo se conserva si es ISO, no posterior a la fecha del
   artículo y a lo sumo 90 días anterior; si no, se omite (campo opcional).
   No se aplica si `raw_text` trae `sources` manuales del operador, ni si no hay
   evidencia que contrastar (`evidence_text` vacío).
2. **`downgrade_unattributed_certainty`** — con `requires_uncertainty_note`, una
   afirmación `confirmed` cuyo texto contiene lenguaje categórico (superlativos,
   «primera/único», «explica», «demuestra», «prueba», «confirmó»…) baja a
   `uncertain`. `uncertain` es solo advisory: no bloquea ni altera la compuerta de
   `disputed`, que sigue leyendo `verified_fact_check`.
3. **Saneamiento de cuerpo** — `strip_stray_hashtags` y `strip_leading_headline_line`
   (línea inicial en negrita o sin puntuación final, ≤160 caracteres, seguida de
   un párrafo).
4. **Advertencias (no bloquean)** — `find_name_inconsistencies` (nombre completo en
   frontmatter ausente del cuerpo cuando solo su apellido aparece) y
   `find_second_person_address`. Se registran con `logger.warning` y se anexan a
   `grounding_notes`. Las cifras, el alcance y las exageraciones sin respaldo ya los
   cubre `editorial/grounding.py` (consultivo) y no se duplican aquí.
## Prompt de enriquecimiento: probado y descartado

Se intentó endurecer `config/prompts.yaml` (`sources` solo con URLs presentes en el
texto, nunca inventar DOI/títulos/fechas, `uncertain` para atribuciones). **No se
incluye.** Una prueba A/B real (2026-11-09) ejecutó `_generate_enrichment_fields`
con `qwen3-next:80b-a3b-instruct-q4_K_M` (el modelo de producción para
enriquecimiento), prompt actual vs. endurecido, 2 repeticiones sobre los cuerpos
originales de #407 y #408 (8 llamadas, todas con JSON válido):

| | Prompt actual | Prompt endurecido |
|---|---|---|
| #407, `sources` | 1 y 1 (solo la fuente original) | 2 y 2: una URL de Cambridge inventada en **ambas** corridas |
| #408, `sources` | 1 y 1 | 1 y 1 |
| `fact_check` atribuido marcado `confirmed` | 1 de 4 corridas | 1 de 4 corridas |

La muestra es pequeña (2 por celda, un modelo), así que no es concluyente, pero no
hay señal a favor del prompt endurecido y la única diferencia visible lo
empeora: el modelo produjo más fuentes inventadas antes del filtro. La regla 1
(`ground_sources`) descartó esas URLs inventadas en las 2 corridas, de modo que la
protección efectiva es la regla determinista. Se retoma el prompt solo con una
evaluación mayor (más corridas y más artículos) y, al cambiar la cadena LLM, con
`make llm-canary`.

## Fuera de alcance

Verificación de existencia de DOI contra Crossref (I/O en el borde; la regla 1 ya
impide que un DOI no presente en la evidencia llegue al frontmatter), titulares que
presentan como hecho una conclusión de datos no publicados, y la paráfrasis cercana.

## Verificación

- `pytest tests/unit/editorial/test_source_integrity.py` — reglas puras, con los
  casos reales de #406/#402/#398/#391 como fixtures.
- `pytest tests/unit/editorial/test_editorial_publication_artifact.py` — cableado
  y compatibilidad (sin `evidence_text` el comportamiento previo no cambia).
- `make lint`, `make type`, `make test`, `make quality-gate`.
- No se lanza ninguna publicación real ni se modifican datos exportados.
