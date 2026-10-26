# Plan 198 — reconciliar intentos de publicación con el estado de GitHub

## Contexto (verificado 2026-10-26)

18 intentos de publicación siguen en `PR_CREATED` y sus artículos en
`processing_status='publishing'`, algunos desde septiembre. Clasificados
contra ambas tablas de recibos y contra GitHub:

| Grupo | Intentos | Causa |
| --- | --- | --- |
| PR integrada, callback nunca recibido | 9 | PR 144–197, 281, 284 |
| PR integrada, callback sin `publication_attempt_refs` | 6 | anteriores a `fbc1a905` |
| PR integrada, hash distinto por commits manuales en la PR | 1 | 3724 / PR 312 |
| PR cerrada sin integrar | 2 | PR 288, 290 |

`reconcile_publication_attempts.py` solo usa evidencia local, así que no los
resuelve. Relajar la correlación por hash resolvería 1 de 18 y debilita una
protección deliberada; se descarta.

## Objetivo

Usar el estado de la PR en GitHub como evidencia de despliegue para cerrar
intentos `PR_CREATED` atascados, de forma auditable e idempotente.

Criterios de aceptación:

1. `scripts/ops/reconcile_publication_attempts.py --github` consulta cada PR
   candidata y:
   - PR **integrada** → intento `COMPLETED` (evento `deployed`) y, si el
     intento es el vigente del artículo, artículo `completed` con
     `published_at = merged_at` y `published_url` = URL del sitio.
   - PR **cerrada sin integrar** → intento `REJECTED` (evento `rejected`) y
     artículo `rejected` si es el intento vigente.
   - PR **abierta**, o consulta fallida → sin cambios; se informa.
2. Cada transición registra `source=github_reconciliation`, número de PR,
   `merged_at`, `merge_commit_sha` y `closed_at` en `publication_events`.
3. `--dry-run` calcula lo mismo sin escribir.
4. Sin `--github` el comportamiento actual no cambia (la evidencia de GitHub es
   opt-in).
5. Una segunda pasada es idempotente: no hay candidatos o no hay cambios.

## Diseño

- **I/O en el borde.** `PublicationReconciliationWorkflow` recibe un proveedor
  opcional `pull_request_state(pr_url) -> PullRequestState | None`. La
  implementación de red es un método nuevo de lectura en `GitHubPublisher`
  (`get_pull_request_state`), que ya gestiona token y timeouts. El workflow
  sigue sin importar clientes de red.
- **Intento vigente.** Se proyecta al artículo solo si el intento es el
  vigente: token `publication_attempt_id` coincidente (regla actual), o, para
  intentos antiguos sin token, que sea el último intento del artículo y el
  artículo no apunte a otro. Si no lo es, solo cambia el intento.
- **Transacción única.** Nuevo método
  `LifecycleRepository.apply_reconciled_pull_request_outcome` que, en una
  sesión, hace el CAS del intento, agrega el evento y proyecta el artículo,
  reutilizando los helpers de los callbacks correlacionados.
- **Orden de evidencias.** Se mantiene: primero replay de recibos, después la
  proyección legacy y, solo si nada resolvió, GitHub.
- **URL publicada.** El sistema guarda la URL de despliegue del sitio (raíz),
  no la del artículo; se mantiene esa convención con
  `https://noticiencias.com/`, configurable con `--site-url`.

## Fuera de alcance

- Correlación por hash de los callbacks (sin cambios).
- Marcar como ajenas las PR manuales (#345, #352): sus recibos se agotan con
  el presupuesto de 5 intentos.
- Programar el reconciliador con un timer: es configuración del operador; se
  documenta el comando.

## Verificación

| Comprobación | Cómo |
| --- | --- |
| PR integrada → COMPLETED + artículo completed con merged_at | test unitario con proveedor falso |
| PR cerrada → REJECTED + artículo rejected | test unitario |
| PR abierta / proveedor devuelve None → sin cambios | test unitario |
| Intento legacy sin token y último del artículo → proyecta | test unitario |
| Intento no vigente → solo intento, artículo intacto | test unitario |
| dry-run sin escrituras | test unitario |
| sin proveedor → comportamiento anterior | suite existente |
| `get_pull_request_state` parsea merged/closed/open y falla con None | test con `respx`/mock de requests |
| gates | `make test`, `make test-contracts`, `make test-boundaries`, `make lint`, `make type`, `make lint-imports` |
| datos reales | backup → `--github --dry-run` → revisión → ejecución → segunda pasada idempotente |
