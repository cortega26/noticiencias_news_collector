# TODO — Plan 078

- [x] Spec (+ resolved NULL-heartbeat nuance)
- [x] `recover_expired_leases(include_queued)` en ambos workflows +
  llamada en ambos `start()`
- [x] Tests: reap expirado, queued fresco intacto + 409, unbeaten
  fresco intacto, unbeaten viejo recuperado (ambos workflows)
- [x] Gates: lint, type (2226 ✓ + ratchet), test (2213 ✓), boundaries
- [ ] Commit + push (+ vigilar CI)
- [ ] Manual: fila 20 → interrupted (hecho fuera de banda el 2026-09-04,
  documentado en error_detail)
