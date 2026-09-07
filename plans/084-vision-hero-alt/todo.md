# TODO — Plan 084 (vision-model hero alt)

Status: spec only. Not started. Sequenced after the social-distribution work
settles; independent of it.

## Preparación

- [ ] Confirmar el modelo multimodal y su límite de tokens/imagen en la
      cuenta de Google AI Studio en uso (`gemini-2.5-flash`).
- [ ] Decidir el presupuesto mensual de llamadas y dónde vive el contador.

## Implementación

- [ ] `infrastructure/llm/gemini_provider.py` — `describe_image_sync(image_bytes, mime_type, prompt)`
- [ ] `editorial/vision_alt.py` — `should_describe`, `build_prompt`, `describe_hero_image`
- [ ] Config `editorial.vision_alt.{enabled,model,timeout_s,monthly_budget}` + carga en settings
- [ ] Caché `data/runtime/vision_alt/<sha256>.json`
- [ ] Hook: `resolve_hero_alt_text` gana `describe_fn` opcional; wiring en `ai_editor.py` ensamblaje de frontmatter

## Verificación

- [ ] Unit: `should_describe` matriz, `build_prompt` contiene restricciones, `describe_hero_image` (caché, excepción→None, salida boilerplate rechazada, happy path)
- [ ] Provider: test de construcción de payload (`inline_data` base64 + mime) + un test live opt-in tras env flag
- [ ] Integración: PNG fixture + alt boilerplate ⇒ `image_alt` = descripción; brief con `draft_alt_text` ⇒ intacto
- [ ] `make lint && make type && make test`; FE `check:image-alt` / `check:hero-images` sin cambios en el corpus

## Cierre

- [ ] Actualizar `plans/README.md` (fila del plan) si se decide ejecutar
- [ ] Codex re-review del PR de contenido que estrene la descripción real
