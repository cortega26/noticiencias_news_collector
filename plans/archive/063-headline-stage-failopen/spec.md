# Plan 063 — Stage 3 headlines: reintento + fail-open ante JSON inválido

## Symptom

Run 17 muere en `STAGE 3: Metadata & Headlines`: el LLM (NVIDIA) responde
en 0.61s sin JSON parseable → `_extract_json` devuelve `{}` →
`HeadlinesSchema(**{})` → `ValidationError` → `ValueError` → el artículo
falla entero (`Engine reported 1 errors`), sin PR. Minutos de pipeline
(editor + critic 8.0) a la basura por un glitch de 0.61s.

## Root cause

`EditorAgent._generate_headlines` (`components/editorial/ai_editor.py:1664`)
hace UN solo intento y propaga cualquier fallo como excepción, que
`_generate_headlines_with_critic` no captura. Contradice la filosofía del
módulo: el critic de titulares ya es fail-open (`_headline_critic_pass`),
`_repair_output` ya rellena `direct`/`question`/`benefit` ausentes, y todo
el consumo posterior es `.get()` con fallbacks (`ai_editor.py:2208-2260`).
Solo el `raise` impide llegar a ese código tolerante.

## Fix

1. `_generate_headlines`: bucle de hasta `_HEADLINE_FORMAT_MAX_ATTEMPTS = 2`
   intentos (inicial + 1 reintento con instrucción de corrección de formato
   añadida al prompt). Cada intento captura cualquier `Exception` de
   send/extract/validate, loguea warning con snippet de respuesta. Si todo
   falla, devuelve el último dict parcial (o `{}`) en vez de lanzar — la
   capa de reparación determinista y los fallbacks `.get()` lo sostienen.
   Mantener el kill-switch `ENABLE_TRANSLATION_GUARD=false`.
2. `_generate_headlines_with_critic`: si la generación devuelve dict vacío
   tras agotar reintentos, saltar el critic (nada que juzgar), warning, y
   devolver `{}` a la capa de reparación. Evita quemar llamadas del critic
   juzgando la nada.
3. Tests (`tests/unit/editorial/test_ai_editor_coverage.py`):
   - Actualizar `test_generate_headlines_schema_failure` y
     `test_generate_headlines_generic_failure` al nuevo comportamiento
     (devuelven parcial/`{}` sin lanzar).
   - Nuevos: reintento-y-éxito (2 llamadas), agotamiento→`{}` apto para
     repair, critic saltado con `{}`.
4. Revisar `tests/verify_phase1.py` (script manual con aserción del
   comportamiento antiguo) y actualizarlo si procede.

## Non-goals

- Endurecer `_extract_json` del provider (la respuesta de 0.61s no traía
  JSON en absoluto — footnote: si el usuario pega el snippet completo del
  warning se reevalúa).
- Hacer los runs resumibles tras reinicio (plan 062 follow-up).
- Cambiar `HeadlinesSchema` (contrato válido; el problema es la robustez,
  no el esquema).

## Verification

- `pytest tests/unit/editorial/test_ai_editor_coverage.py tests/test_editor_agent.py` en verde.
- Baseline de cambio de regla: `make lint && make type && make test`.
- Simulación: `_send_prompt` → basura una vez → JSON válido (recupera);
  basura siempre → `{}` + repair rellena `direct/question/benefit`.
