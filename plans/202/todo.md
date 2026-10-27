# Plan 202: estado

- [x] Diagnóstico del prompt v1 y de las imágenes publicadas
- [x] Spec
- [x] Director de arte, prompt v2 y tests
- [x] Comparación de 4 artículos (malaria, Marte, neandertal, coral): aprobada por el propietario el 2026-10-27
- [x] Estilo de ilustración más estricto (sin render brillante ni partículas)
- [x] Generador con Codex: autorrevisión contra notas de precisión, validación 16:9 ≥1200 px, registro `ai_generated`, tope de intentos
- [x] Arranque en el servidor admin, detrás de `[image_autogen].enabled`
- [x] Gates y PR
- [x] E2E en carpeta aislada (coral, 2026-10-27): el primer intento agotó los 15 min en `/tmp` sin dejar registro; con carpeta propia y registro de fallos, imagen registrada en 162 s
- [ ] Primer artículo real resuelto solo tras reiniciar `make admin`

## Pendiente conocido

- Los encargos nuevos se siguen creando con el prompt v1 (lo ve quien sube
  una imagen a mano en el admin). El generador automático siempre usa v2.
- `make type` falla en `news_collector/storage/maintenance.py:26`; el error ya
  existía en main y no lo toca este plan.
