# Plan 067 — Uncertainty counterweight enforcement (voz §2.4.3)

## Finding (evidencia, no hipótesis)

La voz exige: titular con curiosity-gap sobre hallazgo preliminar ⇒
`uncertainty_note` obligatoria Y visible. El frontend ya la renderiza
(`TrustPanel.astro`: callout ámbar si `requires`, línea discreta si no).
Pero el backend no garantiza el invariante (`ai_editor.py:2404-2411` solo
copia la nota `if uncertainty_note and requires`):

- En producción HOY: 2 de 3 artículos con `requires_uncertainty_note: true`
  NO traen `uncertainty_note` (posts 2026-04-24 y 2026-05-23) → el flag
  dice "obligatorio" pero la UI muestra nada. Violación silenciosa.
- Si el LLM da nota sin flag, se descarta (`if ... and requires`).
- `pattern_used` nunca se persiste; solo vive en memoria para el critic.

## Design

Nuevo módulo puro `news_collector/editorial/uncertainty.py` (stdlib +
logger; sin red/DB/LLM):

- `hook_needs_counterweight(pattern_used)`: True solo para
  `curiosity_gap` (normalizado: case/espacios↔guion-bajo).
- `confidence_suggests_preliminary(confidence)`: primera palabra (antes
  de espacio/guion/signos) en `moderada*|media*|baja*` (insensible a
  mayúsculas). `confidence` real es texto libre ("Moderada — ..."); `Alta`
  u otro ⇒ False (fail-open: no forzar).
- `GENERIC_UNCERTAINTY_NOTE`: caveat genérico honesto en español.
- `resolve_uncertainty_counterweight(headlines, confidence)
  -> tuple[bool, str | None]`:
  1. `requires = bool(headlines.requires)`; `note` = nota si no vacía
     (¡aunque `requires` sea False — hoy se descarta, se pierde contenido!).
  2. Si no `requires` pero hook curiosity-gap + confianza preliminar ⇒
     `requires = True` + warning (contrapeso de la voz).
  3. Si `requires` y sin nota ⇒ nota genérica + warning (fail-open: una
     caveat genérica visible es mejor que un flag invisible).
  4. Retorna `(requires, note or None)`.

Integración (`ai_editor.py`, bloque ~2404, 6 líneas → llamada):
`requires, note = resolve(...); model_dict["requires..."] = requires;
if note: model_dict["uncertainty_note"] = note`.
Sin cambios de contrato (mismas claves), sin llamadas LLM extra, sin
bloqueos. Stakes/question NO fuerzan (la voz nombra curiosity-gap;
extensión = follow-up).

## Non-goals

- Cambios en frontend (ya renderiza ambos casos — verificado).
- Backfill de los 2 posts históricos violados (contenido publicado en el
  otro repo: decisión editorial, se reporta, no se toca).
- Hacer `pattern_used` persistente / bloquear publicación / reescribir notas.

## Verification

- `tests/unit/editorial/test_uncertainty.py` (nuevo): matriz
  requires×note×pattern×confidence incl. variantes ("Curiosity Gap",
  "Moderada-alta", `headlines=None`), nota-sin-flag se conserva.
- 2 tests de integración `process_article` (flag sin nota → caveat en
  salida; curiosity-gap + Moderada sin flag → requires + caveat).
- Existentes intactos (`test_uncertainty_note_emitted_when_required`,
  list/shape tests). `make lint && make type && make test`.
