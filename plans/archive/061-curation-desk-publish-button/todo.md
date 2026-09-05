- [x] Diagnosticar (botón condicional + estilo fantasma + sin botón en detalle)
- [x] Escribir spec.md
- [x] Reescribir `.queue-publish-btn` en CSS plano prominente (+ estado disabled)
- [x] `renderQueue()`: botón siempre visible, disabled con motivo si no publicable
- [x] `renderDetail()`: botón primario `✨ Refine & publish` + listener + atajo `p`
- [x] `setPublishInFlight()`: incluir el botón del detalle (solo `data-armed`)
- [x] `article.astro`: botón publicar equivalente
- [x] Backend: `AdminArticleDetail.publishable/export_score` + pasar
  `load_export_candidate_scores()` en `admin_article_detail` + test
  `test_admin_article_detail_mirrors_publishable_candidacy`
- [x] Estilos de cola a `global.css` (el scope de Astro no alcanza al DOM
  dinámico — causa raíz del botón "invisible")
- [x] `npm run check && npm test && npm run build` en apps/admin
- [x] `make lint && make type && make test && make test-contracts && make test-boundaries`
- [x] Verificación en vivo (20/20 botones, detalle habilitado, captura)
