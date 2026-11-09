# Plan 211 — Integridad de fuentes y afirmaciones antes de sellar el borrador

## Origen

Revisión editorial de los PRs de contenido #406, #402, #398 y #391 del frontend
(2026-11-08). Todos llegaron como borradores con defectos que ninguna compuerta
del pipeline detectó:

| Defecto observado | PR | Compuerta que faltaba |
|---|---|---|
| DOI y título de paper inventados (404), fecha de fuente de 2024 en una nota de 2026, "fuente" que era la portada de una universidad | #406 | `sources` no se contrasta con la evidencia ingerida |
| Afirmaciones del equipo, disputadas por una experta, marcadas `confirmed` ("más antigua y sólida", "explica el sesgo sexual") | #406, #402 | `fact_check` confirma lenguaje categórico aun con nota de incertidumbre |
| Cuerpo con métodos, contexto y detalles que la fuente ingerida (solo resumen y autores) no contiene | #402, #398 | Parcial: `grounding.py` (consultivo) cubre cifras y alcance; el prompt de enriquecimiento se endurece |
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
5. **Prompt de enriquecimiento** (`config/prompts.yaml`) — `sources` solo con URLs
   presentes en el texto proporcionado o la fuente del artículo; nunca inventar
   DOI, títulos ni fechas; `date` solo si el texto la da; `fact_check`: usar
   `uncertain` para afirmaciones que la fuente atribuye a los autores.

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
