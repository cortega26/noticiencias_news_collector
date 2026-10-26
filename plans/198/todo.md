# Plan 198 — estado

- [x] Clasificar los 18 intentos `PR_CREATED` (recibos + GitHub)
- [x] Spec
- [x] `GitHubPublisher.get_pull_request_state` + tests
- [x] `LifecycleRepository.apply_reconciled_pull_request_outcome` + tests
- [x] Rama GitHub en `PublicationReconciliationWorkflow` + tests
- [x] Flags `--github` / `--site-url` en el script
- [x] Gates: test, contracts, boundaries, lint, type, lint-imports
- [ ] PR y CI
- [ ] Datos reales: backup, dry-run, revisión del titular, ejecución, segunda pasada
- [ ] Regenerar la copia del código del timer

## Notas

- Sin `GITHUB_TOKEN`, la cabecera `Authorization` con token vacío provocaba 401; `get_pull_request_state` ahora hace lectura anónima (test incluido).
- Dry-run real (2026-10-26): scanned=18, completed=16, rejected=2 (PR 288, 290), stale_pr_open=0.
