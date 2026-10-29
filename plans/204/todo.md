# Plan 204 tasks

- [x] Diagnosticar el fallo de `make admin` con el servicio activo.
- [x] Detección de stack existente con modos reuse/restart/heal/status.
- [x] Marca de dueño en la API; `cleanup` solo detiene una GUI propia.
- [x] Fallo de GUI explícito y registrado; traps que terminan el script.
- [x] Registro de eventos y aviso ante fallos recurrentes.
- [x] Unidad systemd en modo restart y ayuda del Makefile.
- [x] Tests con stubs y verificación en vivo de status/reuse.
- [x] Probar `restart` y un arranque completo (2026-10-29): unidad instalada
  con `ADMIN_STACK_MODE=restart`, `daemon-reload` y reinicio; API y GUI
  responden. `make admin` con el servicio activo lo detecta (`status`, salida 0)
  y lo reutiliza sin duplicar. PR #417 (fusionado; también corrige que la
  reutilización exigiera `node_modules`).
