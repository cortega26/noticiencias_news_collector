# Plan 198 — estado

- [x] Clasificar los 18 intentos `PR_CREATED` (recibos + GitHub)
- [x] Spec
- [x] `GitHubPublisher.get_pull_request_state` + tests
- [x] `LifecycleRepository.apply_reconciled_pull_request_outcome` + tests
- [x] Rama GitHub en `PublicationReconciliationWorkflow` + tests
- [x] Flags `--github` / `--site-url` en el script
- [x] Gates: test, contracts, boundaries, lint, type, lint-imports
- [x] PR y CI
- [x] Datos reales: backup, dry-run, revisión del titular, ejecución, segunda pasada
- [x] Regenerar la copia del código del timer

## Notas

- Sin `GITHUB_TOKEN`, la cabecera `Authorization` con token vacío provocaba 401; `get_pull_request_state` ahora hace lectura anónima (test incluido).
- Dry-run real (2026-10-26): scanned=18, completed=16, rejected=2 (PR 288, 290), stale_pr_open=0.
- Ejecución real (2026-10-26, backup `backups/news_v3.pre-github-reconcile-20261026-152028.db`): 16 COMPLETED, 2 REJECTED, 18 eventos `github_reconciliation`; segunda pasada scanned=0; `integrity_check` ok.
- Timer `noticiencias-webhooks-pull` apuntado a la copia `noticiencias-serving-5ddaee39` (main con PR #403).
