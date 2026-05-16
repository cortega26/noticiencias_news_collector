# Todo — Editorial Prompts & Critic Overhaul

Consultar `spec.md` antes de cada cambio.

## Hecho en esta sesión

- [x] Reescribir prompt del traductor (español neutro anclado, filtro de ruido por principio, glosario extendido)
- [x] Reescribir prompt del editor (estructura adaptativa, repertorio aperturas/cierres, anti-tics IA, shareability, cierre con puente, voz de marca, user_template para contexto)
- [x] Añadir prompt `editor_critic` (7 dimensiones, umbrales, JSON estricto)
- [x] `_adapt_editorial` y `_repair_editorial` aceptan `context=None`
- [x] Helper `_format_editor_context_block`
- [x] Método `_critic_editorial_pass` con feature flag `ENABLE_EDITORIAL_CRITIC` y fail-open
- [x] Helper `_extract_editorial_critic_json` (cast tipado)
- [x] `process_article` construye `editor_context` y lo pasa por toda la cadena
- [x] Stage 2.6 integrada con 1 retry vía `_repair_editorial`
- [x] Tests actualizados: 5 en `test_editor_agent.py`, 1 en `test_editor_agent_critic_recovery.py`, 2 en `test_per_phase_models.py`
- [x] `make lint` PASS, `make test` PASS (964), `make test-contracts` PASS (47)
- [x] `spec.md` actualizado

## Pendiente / próximas iteraciones

- [ ] Few-shot canónico en el prompt del editor — requiere elegir 2-3 artículos ejemplares
- [ ] Persistir score del `editor_critic` por artículo (paralelo al auditor) para serie temporal
- [ ] Calibrar umbrales del `editor_critic` tras 1-2 semanas en producción
- [ ] Considerar mover el prompt hardcodeado del `_critic_pass` técnico a `prompts.yaml` (manteniendo strings literales que los tests de `test_terminology.py` esperan)
