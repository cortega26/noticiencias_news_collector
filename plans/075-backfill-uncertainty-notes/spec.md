# Plan 075 — Backfill uncertainty notes (2 posts históricos)

## Contexto

Dos posts publicados llevan `requires_uncertainty_note: true` sin
`uncertainty_note` (hallazgo del plan 067). Son contenido del repo
frontend — por regla no se escribe ahí directamente: este plan entrega
los diffs exactos para aplicar a mano o vía PR del frontend.

## Notas redactadas (específicas, una frase cada una)

1. `2026-04-24-...-prompt-injections-on-the-web.md`: el propio cuerpo
   dice que solo se observaron experimentos, no ataques masivos. Caveat:
   casos mayormente experimentales/pruebas de concepto; riesgo
   prospectivo ligado a la integración cotidiana de asistentes.
2. `2026-05-23-...-tallest-rocket-ever.md` (schema v1, clave opcional
   igualmente válida): conclusiones sobre un único vuelo con anomalías
   y sin recuperación de etapas; repetibilidad y aptitud tripulada
   pendientes.

## Verificación

- Inserción justo tras `requires_uncertainty_note: true` en cada
  frontmatter; sin tocar nada más. Frontend ya renderiza ambos casos
  (TrustPanel, verificado en 067).
