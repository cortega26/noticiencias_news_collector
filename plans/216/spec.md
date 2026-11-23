# Plan 216 · Vincular acciones de Triage con el artículo visible

**Base** `ffebfc9b3c8ff91cd001b3e2cc1c085ab6acbfc6` · 2026-11-22 · **Prioridad** P1 · **Riesgo** medio · **Esfuerzo** M · **Hallazgo** C02

## Resultado

El panel solo habilita acciones sobre un detalle que corresponde a la selección actual. Una respuesta anterior, un atajo del navegador o una recarga tras login carecen de efectos sobre el artículo equivocado.

## Estado y alcance

- `apps/admin/src/pages/triage.astro:374–409` muta filtro y cursor antes de desestimar el nuevo fetch por `loading`. El listener de `auth:ready` se instala desde un clic. En `522–539`, `select` actualiza el ID visual mientras conserva el detalle anterior hasta el resultado. El handler de `743–786` usa ese detalle y omite modificadores, repetición y estado de login.
- En un DOM simulado que ejecutó el script real, las acciones recientes de A siguieron habilitadas al seleccionar B. Un resultado de auditoría de A modificó el detalle de B, y un fetch anterior de «Listos» colocó su cursor bajo «Rechazados».
- Editar `apps/admin/src/pages/triage.astro` y añadir una prueba de interacción de script en `apps/admin/src/lib/` con el Vitest y Happy DOM existentes. Reusar el patrón de guard de identidad que aplica esta página en su sondeo de publicación cerca de la línea 1127. El API de operaciones, el esquema OpenAPI, la lógica de publicación backend y el polling de recolección quedan fuera.

## Decisiones y verificación

1. Registrar `auth:ready` una vez durante inicialización. Separar cambio de filtro y «Cargar más». Cada pedido lleva el filtro, la generación y el cursor que lo originaron. Solo la generación vigente puede aplicar datos, cursores, fallos o finalizar su estado de carga. Dos «Cargar más» sobre el mismo cursor producen una sola adopción de página.
2. Invalidar el detalle y deshabilitar sus controles inmediatamente al cambiar selección, limpiar filtro o cerrar. Modelar carga, error y listo de forma explícita. Atajos y botones validan que el detalle listo y la selección compartan ID. Cada operación captura su identidad. Puede terminar en backend si el operador cambia de selección, pero su respuesta no modifica el nuevo panel. Respetar controles editables, evento consumido, repetición y atajos con modificadores. Con la pantalla de login visible, los atajos de mutación quedan inactivos.
3. Caracterizar con API simulada y promesas controladas. Cubrir A → B pendiente y fallido, A → B → A fuera de orden, auditoría de A que termina en B, doble petición de paginación, cambio de filtro, reintento tras primer login, acción válida sobre la selección activa y modificadores de navegador. Afirmar el ID de cada petición o su ausencia, y el cursor y estado visible. Evitar llamadas a una API real.
4. En `apps/admin`, ejecutar `npm test && npm run check && npm run build && npm run contracts:check`. La auditoría ejecutó los primeros tres comandos en copia aislada con la instalación local y verificó 97 tests. Comprobar que el contrato generado se mantiene y que una interacción de teclado real en preview local respeta la selección y el login.

Comprobar deriva con `git diff ffebfc9b..HEAD -- apps/admin/src/pages/triage.astro apps/admin/src/lib`. Si el panel dejó de ser dueño de la identidad o ahora dispone de integración de navegador oficial, adaptar la prueba antes de editar. Actualizar la fila 216 con evidencia del SHA.
