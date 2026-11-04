# Plan 210 — Dependencias npm de desarrollo

## Objetivo

Resolver los avisos moderados de glob y minimatch que bloquean la auditoría npm del panel y de la evaluación editorial, preservando el funcionamiento de ambos consumidores y sin modificar los datos o servicios del usuario.

## Alcance y decisiones

Actualizar las resoluciones de dependencias transitivas en `apps/admin` y `tools/editorial_eval`, manteniendo Node 24 y evitando degradar versiones o desactivar auditorías. Registrar las versiones reales en los lockfiles y comprobar compatibilidad, en particular del generador OpenAPI y del replay editorial.

El gate de calidad también señala como contraseña codificada el valor vacío predeterminado de `AdminClient`. Representar la ausencia de token con `None`, conservando la omisión del encabezado de autorización en desarrollo y el envío de tokens explícitos; comprobar ambos comportamientos existentes.

## Validación

Ejecutar npm ci y auditoría de ambas carpetas; lint, check, tests, build y contracts:check del panel; y replay editorial offline de baseline y candidato. Ejecutar los controles backend pertinentes, `make quality` y `make prepush` antes del push. Registrar fallos o pruebas omitidas; no declarar corregido lo no verificado.
