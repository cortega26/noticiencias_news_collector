# Spec: Editorial Prompts & Critic Overhaul

## Goal

Mejorar la calidad editorial percibida de los artículos publicados por
Noticiencias (engagement, memorabilidad, shareability, fidelización),
sin tocar el contrato `frontend_schema` ni la arquitectura de pipeline.

## Cambios

### 1. `config/prompts.yaml`

| Bloque | Cambio |
|---|---|
| `translator` | Reescrito. Ancla "español neutro LatAm" con reglas explícitas (léxico, tú, tiempos verbales). Filtro de ruido por principio (no por enumeración). Glosario anti-alucinación extendido (subject, random, significant, theory). Output limpio sin preámbulos. |
| `editor` | Reescrito. Estructura adaptativa por tipo de artículo (A estudio, B anuncio, C tendencia, D política/perfil). Repertorio explícito de aperturas y cierres legítimos. Anti-tics-de-IA explícito (triadas paralelas, "no solo X sino también Y", "es importante notar", etc.). Voz de marca anclada ("tú", peer-to-peer). Criterio de shareability. Cierre con puente conceptual. Nuevo `user_template` para inyección de contexto situacional. |
| `editor_critic` | **Nuevo**. Crítico editorial bloqueante con 7 dimensiones (hook, clarity, structure, rigor, voice, shareability, closing), umbrales explícitos y feedback accionable. Output JSON estricto. |
| `auditor`, `headline` | Sin cambios. |

### 2. `news_collector/components/editorial/ai_editor.py`

- `_adapt_editorial(translated, context=None)` — ahora acepta contexto situacional opcional (título original, summary, source, categoría) y lo renderiza en el user-prompt vía `user_template` del YAML.
- `_repair_editorial(base, feedback, context=None)` — mismo cambio, para que las reescrituras mantengan el contexto.
- `_format_editor_context_block(context)` — nuevo helper estático que produce el bloque de contexto en markdown compacto, omitiendo campos vacíos.
- `_critic_editorial_pass(content, context=None)` — **nuevo**. Stage 2.6. Llama al prompt `editor_critic`, parsea el JSON, decide aprobar o devolver con feedback accionable.
  - Feature flag: `ENABLE_EDITORIAL_CRITIC` (default `true`). Si `false`, retorna pass directo.
  - Si el prompt no está configurado (tests con `_load_prompts={}`), no se ejecuta.
  - Fail-open: ante error de infra/parsing, aprueba y deja la responsabilidad al `auditor`.
- `_extract_editorial_critic_json(text)` — helper para parsear el JSON del editor_critic (distingue por presencia de `approved`/`average`).
- `process_article` — construye `editor_context` después de sanitizar el contenido, lo pasa a stage 2 (`_adapt_editorial`), stage 2.5 (`_repair_editorial`), y ejecuta el nuevo stage 2.6 (`_critic_editorial_pass`) con 1 retry vía `_repair_editorial`. Tras agotar retries, publica con caveat en log (no bloquea, porque el critic técnico y el placeholder validator ya pasaron y el auditor sigue corriendo).

### 3. Tests actualizados

- `tests/test_editor_agent.py` — añadido mock de `_critic_editorial_pass` en los 5 tests de `process_article` para que la nueva stage no consuma tiempo.
- `tests/e2e_editorial_guardrails/test_editor_agent_critic_recovery.py` — `_adapt_editorial` mock con `*args, **kwargs`; añadido bypass de `_critic_editorial_pass`.
- `tests/unit/test_per_phase_models.py` — dos casos: `_adapt_editorial` mock con `*args, **kwargs`; añadido mock de `_critic_editorial_pass`.

## Verificación

| Gate | Resultado |
|---|---|
| `make lint` | PASS (459 archivos, sin warnings) |
| `make test` | PASS (964 passed, 3 skipped esperados) |
| `make test-contracts` | PASS (47 passed) |
| `mypy ai_editor.py` | 4 errores preexistentes, 0 nuevos introducidos por esta sesión |

## Compatibilidad

- `_critic_pass` técnico **intocado**: tests/test_terminology.py sigue dependiendo de sus strings literales y siguen pasando.
- `_adapt_editorial` y `_repair_editorial` con `context=None` por default — invocaciones antiguas siguen funcionando.
- Feature flag `ENABLE_EDITORIAL_CRITIC=false` desactiva el nuevo gate sin redeploy.
- El crítico editorial **no bloquea publicación**: rechaza, dispara 1 retry de reescritura, y si sigue rechazando, publica con warning. Esto evita falsos positivos del LLM bloqueando contenido válido.

## Non-Goals

- Modificar `frontend_schema` o el contrato Astro.
- Tocar el auditor o headline.
- Refactor de RefineryEngine.
- Few-shot canónico en el prompt del editor (requiere identificar 2-3 artículos publicados ejemplares; pendiente input del usuario).

## Próximos pasos sugeridos

1. **Curar few-shot canónico**: elegir 2-3 artículos ya publicados que ejemplifiquen voz/estructura/cierre Noticiencias e incluirlos al final del system-prompt del editor. Subirá nivel de la voz reconocible.
2. **Calibrar umbrales del `editor_critic`**: dejar correr 1-2 semanas, revisar logs de "EDITORIAL CRITIC REJECTED" + cómo queda el output tras retry. Si demasiado permisivo, subir promedio mínimo o `rigor_score` mínimo. Si demasiado estricto, bajarlos.
3. **Métrica de tasa de aprobación**: persistir score editorial por artículo (similar al auditor) para tener serie temporal y detectar regresiones de prompt.
