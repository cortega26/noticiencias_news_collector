# Plan 201 — la espera de imagen usa el encargo de su checkpoint

## Contexto

- `ImageBriefStore.ready_for_article(article_id)` ignoraba el slug guardado en
  el checkpoint y tomaba el encargo más reciente del artículo. Si un artículo
  tenía dos encargos, uno ya listo podía liberar la espera de otro que no lo
  estaba.
- `PublicationCheckpointRepository.claim` capturaba el `IntegrityError` del
  índice de publicación única, pero `get_session` ya lo había registrado como
  ERROR. Era ruido en cada intento del reanudador mientras otra publicación
  ocupaba el turno.
- Al reanudar desde un checkpoint no hay llamadas a LLM, y el informe decía
  "¿no configurado? scoring heurístico", lo que sugería una falla.

## Cambios

1. `ready_for_article(article_id, slug=None)`: con slug, solo cuenta ese
   encargo y debe pertenecer al artículo. El reconciliador pasa
   `cp.image_brief_slug`.
2. `claim` captura el conflicto dentro de la sesión y hace rollback antes de
   que `get_session` lo registre.
3. El mensaje del informe vacío menciona la reanudación desde un checkpoint.

## Verificación

- Test nuevo `test_checkpoint_slug_selects_its_own_brief`.
- Suites de observability, storage y workflows; lint; docs.

## Fuera de alcance

- El log duplicado venía de dos servidores admin activos a la vez. Se resolvió
  reiniciando `make admin`: hoy hay un solo proceso. El claim en la base de
  datos ya impedía publicaciones dobles.

## Fuentes "rotas" (revisión 2026-10-27)

- `bair_blog`: el feed volvió (200, 10 entradas). Se retira la blacklist del
  plan 105.
- `nih_news`: sigue en 403 para clientes automáticos. Se mantiene en la blacklist.
- `reddit_science`: `manual_only`, requiere credenciales OAuth que no están
  configuradas. Se mantiene así.
