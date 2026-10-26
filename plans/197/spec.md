# Plan 197 — un solo backlog por repositorio

## Objetivo y alcance

El trabajo abierto estaba repartido en backlogs con estados contradictorios (por ejemplo, la auditoría de marzo decía «18 hallazgos abiertos» cuando solo queda uno). Este plan deja **un único archivo de trabajo abierto por repositorio**: `docs/BACKLOG.md`, en este repositorio y en el frontend.

Es un cambio solo de documentación. No toca código, contratos ni configuración.

## Qué se centraliza y qué no

- **Se centraliza:** el trabajo abierto, su dueño, su estado con fecha y fuente y su criterio de cierre.
- **No se fusiona:** el ledger `plans/README.md` (estado de cada plan, validado por `make plans-ledger-check`) ni los `spec.md` y `todo.md` por plan o tarea que exige `docs/AGENTS.md` §0.1. Son registros de ejecución; el backlog los enlaza.
- **Se archivan** en `docs/archive/backlogs/` los backlogs cerrados: `docs/dev/BACKLOG.md` (renombrado `dev-BACKLOG.md`; sus 4 ítems abiertos pasaron a `docs/BACKLOG.md` §4) y `docs/dev/source-of-truth-backlog.md`.
- **Se conserva en su sitio** `docs/audits/remediation/backlog.md` (16 ítems, todos cerrados), con un aviso de registro cerrado. Se corrigió `docs/audits/Audit_Backlog.md` y la referencia «source of truth» de `docs/audits/Audit_Master_Plan.md`.
- **No se tocan** los artefactos históricos: `plans/081/tests/inventory.json`, `archive/**`, `plans/archive/**`.

## Reglas de contenido

- Cada ítem lleva dueño, estado con fecha y fuente, y criterio de cierre.
- Si dos fuentes se contradicen, se escribe «por verificar»; no se resuelve por suposición.
- Los criterios retirados del gate de AdSense (2,5 posts por semana, 8 semanas, ≥30 artículos, 95 % de indexación) no reaparecen. El gate vive en el backlog del frontend.

## Verificación

1. `scripts/check_doc_drift.py` (`make docs-check`) en verde con `docs/BACKLOG.md` y las referencias corregidas (`README.md`, `docs/INDEX.md`).
2. `scripts/validate_plans_ledger.py` (`make plans-ledger-check`) en verde con la fila 197.
3. `audit/00_inventory.json` regenerado con `scripts/generate_inventory.py` y `--fail-on-drift` en verde.
4. Búsqueda de las rutas antiguas (`docs/dev/BACKLOG.md`, `docs/dev/source-of-truth-backlog.md`) sin referencias activas fuera de registros históricos.
