# Plan 065 — Readability gates (deterministas, sin LLM)

## Goal

Dar al pipeline una medida objetiva de legibilidad para el "lector hispano
no especialista" (EDITORIAL_VOICE.md §2): hoy no existe ninguna — solo un
heurístico crudo de longitud de frase en `heuristic_scorer.py:34`. Todo
determinista (sin coste LLM), advisory (fail-open, no bloquea publicación),
observable (logs + attempt summary que ya llega al API).

## Design

Nuevo módulo puro `news_collector/editorial/readability.py` (solo stdlib;
`news_collector/editorial/__init__.py` está vacío → sin riesgo circular):

1. `count_syllables_es(word)`: grupos vocálicos con reglas de
   diptongo/hiato/triptongo en español (fuertes a,e,o; débiles i,u,ü;
   tilde en débil rompe; fuerte+fuerte separa; `h` inter vocálica
   transparente; `y` final = vocal).
2. `fernandez_huerta_ifh(s,w,f) = 206.84 − 60·S/P − 1.02·P/F` y
   `szigriszt_ifsz(s,w,f) = 206.84 − 62.3·S/P − P/F` (verificadas contra
   bibliografía; IFSZ primaria por mejor validación).
3. `readability_grade(score)`: bandas FH (≥90 muy fácil … <15 muy difícil).
4. `readability_suitability(score) = clamp((score−15)/60, 0, 1)` — 1.0 ≈
   prensa general (≥75), 0.0 ≈ académico (<15).
5. `analyze_body_readability(markdown) -> ReadabilityReport`: quita
   frontmatter local, cuenta palabras/frases (con guardia de abreviaturas
   es + decimales)/sílabas, devuelve dataclass con ifsz/ifh/grade/etc.
6. `check_headline(headline) -> list[HeadlineIssue]`: longitud (20–110),
   palabras en mayúsculas (allowlist de siglas), adjetivos especulativos
   de la voz 2.4 no citados entre comillas, frases clickbait, punto final,
   `!!`. Todo `warn`, nunca bloquea.

## Integration (2 costuras, ambas aditivas)

- `refinery_engine.py::process_single_article`, tras
  `record_stage("editor_refinement", True)`: calcula el report sobre
  `refined_content` y `record_stage("readability", True, ...)`. Los
  `details` son `Dict[str, Any]` (sin cambio de contrato) y `stages` ya
  viaja en el summary del API (`publication_run_workflow.py:306`).
- `ai_editor.py::process_article`, tras `_generate_headlines_with_critic`:
  `check_headline(headlines.get("direct", ""))` → un `logger.warning` por
  issue (advisory; el critic LLM sigue siendo el juez de calidad).

## Non-goals

- No toca scoring/selección (shortlist intacta), no bloquea nada, no cambia
  contratos, no UI en Curation Desk (los stages ya llegan al API: follow-up
  barato).
- No reescribe titulares automáticamente (solo avisa).

## Verification

- `tests/unit/editorial/test_readability.py` (nuevo): tabla de ~25
  palabras con conteo silábico, IFSZ de textos de referencia con valores
  esperados aproximados, headline checks (incl. adjetivo citado = pass).
- Test en `test_refinery_engine.py`: `process_single_article` con editor
  mock registra etapa `readability` con valores sanos (redirigiendo
  `publication_attempts_dir` a tmp).
- `make lint && make type && make test`.
