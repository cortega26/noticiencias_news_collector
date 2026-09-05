# TODO — Plan 066

- [x] Spec (scope, contracts, page, non-goals, verification)
- [x] Contracts: `AdminQuality*` in `contracts/admin.py`
- [x] Endpoint `GET /v1/admin/quality/recent` in `serving/api.py`
- [x] Serving test (3 seeded runs + limit 422)
- [x] Frontend: `types.ts` + `api.ts` + `pages/quality.astro` + nav
- [x] Gates: lint/type(2168)/test(2155)/test-contracts/test-boundaries +
  admin check/test/build
- [x] Live snapshot of `/quality` on dev stack (6 real runs, null-tolerant)

## Follow-up descubierto en vivo

- Los runs que mueren por excepción inesperada (p. ej. run 17) no
  persisten attempt summary (`persist_attempt` solo se llama en retornos
  `False` explícitos) → la fila sale sin checklist de etapas. Para que el
  review loop cubra justo los fallos interesantes, persistir las etapas
  acumuladas también en la rama de excepción de `process_articles`.
  Propuesto para 067 o fix dedicado.
