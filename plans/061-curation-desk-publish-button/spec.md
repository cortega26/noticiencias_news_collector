# Plan 061 — Curation Desk: botón Publicar prominente y siempre visible

## Goals

1. El botón `Refine & publish` de cada tarjeta de la cola sea inconfundible
   (botón sólido ámbar a ancho completo, no texto sutil outline).
2. El botón exista **siempre**: si el artículo no es publicable se muestra
   deshabilitado con el motivo en el `title` (antes desaparecía del DOM y el
   usuario concluía que la opción no existe).
3. El panel de detalle (derecha) y la vista `Full view` ganan su propio botón
   `✨ Refine & publish` — hoy no tienen ninguno y es el otro lugar donde el
   usuario lo busca.
4. Sin cambios de contrato/API: se reutiliza `startPublish({articleId})`
   (`POST /v1/admin/publish`) y el campo `publishable` ya servido.

## Diagnóstico

- `triage.astro:264-279`: el botón solo se renderiza `if (item.publishable)`.
  En cualquier otro filtro/estado el DOM no contiene nada → "NO existe".
- `.queue-publish-btn` (`triage.astro:90-98`) es un estilo `@apply` outline
  fantasma en mono 11px; en la captura en vivo se ve como texto plano
  alineado a la derecha, indistinguible de un metadato.
- `renderDetail()` (`triage.astro:326-414`) no tiene acción de publicar.
- `article.astro` (Full view) tampoco tiene acción de publicar.

## Implementation

Archivo: `apps/admin/src/pages/triage.astro` (+ `article.astro` si es trivial).

1. Reescribir `.queue-publish-btn` en CSS plano (sin `@apply`, siguiendo el
   patrón de `.btn-primary` en `styles/global.css`): fondo ámbar sólido,
   texto ink-950, bold, uppercase, ancho completo, `margin-top`. Variante
   `.is-disabled` (o `:disabled`): fondo/ink apagado, cursor not-allowed,
   siempre ocupando el mismo espacio.
2. `renderQueue()`: renderizar el botón **siempre**. Habilitado si
   `item.publishable`; si no, `disabled` + `title` con el motivo
   (`publishing` → "Already in flight"; `published_url` → "Already
   published"; resto → "Not in the current export shortlist").
3. `renderDetail()`: añadir `<button class="btn-primary"
   data-action="publish">✨ Refine & publish <span class="kbd">P</span></button>`,
   misma regla enabled/disabled + motivo. Cablear listener →
   `doPublish({articleId: detail.id})`.
4. `setPublishInFlight()`: deshabilitar también `[data-action="publish"]`.
5. Atajo `p` → publica el seleccionado si es publicable; actualizar el
   subtítulo del header (`… · P PUBLISH`).
6. `article.astro`: añadir botón equivalente que llame a `startPublish`.

## Hallazgo en vivo (backend)

El endpoint de detalle `GET /v1/admin/articles/{id}` **no devuelve**
`publishable` ni `export_score`:

- `news_collector/contracts/admin.py`: `AdminArticleDetail` no declara esos
  campos (solo existen en `AdminArticleListItem`).
- `news_collector/serving/api.py:1053`: `admin_article_detail` llama a
  `_build_admin_list_item(row)` **sin** `export_scores`.

Verificado: `GET /v1/admin/articles/492` → sin claves `publishable` /
`export_score`, mientras la lista sí devuelve `"publishable": true`.
Sin este fix, cualquier botón del detalle/Full-view nace deshabilitado con
un motivo falso. Fix aditivo y compatible (campos con default):

1. `AdminArticleDetail`: añadir `publishable: bool = False` y
   `export_score: Optional[float] = None`.
2. `admin_article_detail`: pasar `load_export_candidate_scores()`.
3. Validación extra por cambio de contrato/serving: `make test-contracts`
   y `make test-boundaries` además de la base.

- `cd apps/admin && npm run check && npm test && npm run build`.
- Recargar `http://localhost:4321/triage` (filtro PUBLISHABLE y otro filtro):
  comprobar con snapshot que cada tarjeta tiene su botón y que el detalle
  muestra el botón primario; captura de pantalla.
- Probar click en un candidato real solo si el usuario lo pide (abre un PR
  real); por defecto verificar hasta el `renderPublishStatus("Starting…")`
  con `dry_run` o inspección de red.
