# A6 Release, Environment, and Change Safety
Last updated: 2026-01-02

## Scope
- c:\Users\corte\VS Code Projects\noticiencias_news_collector
- c:\Users\corte\VS Code Projects\noticiencias

## Evidence reviewed
- c:\Users\corte\VS Code Projects\noticiencias_news_collector\.github\workflows\ci.yml
- c:\Users\corte\VS Code Projects\noticiencias_news_collector\.github\workflows\release.yml
- c:\Users\corte\VS Code Projects\noticiencias_news_collector\docs\database_deployment.md
- c:\Users\corte\VS Code Projects\noticiencias_news_collector\news_collector\config\settings.py
- c:\Users\corte\VS Code Projects\noticiencias\.github\workflows\jekyll.yml
- c:\Users\corte\VS Code Projects\noticiencias\.github\workflows\sync-published.yml
- c:\Users\corte\VS Code Projects\noticiencias\_config.yml

## Release pipeline summary
### noticiencias_news_collector
- CI runs lint, type check, config validation, unit tests, e2e, perf, and healthcheck jobs (`.github/workflows/ci.yml`).
- Release workflow builds changelog on tags and produces container artifacts (`.github/workflows/release.yml`).
- Config validation is enforced in CI (config manager + `make config-validate`).

### noticiencias (site)
- GitHub Pages build and deploy on main, includes `jekyll build` and `htmlproofer` (`.github/workflows/jekyll.yml`).
- Sync workflow updates collector DB on post changes (`.github/workflows/sync-published.yml`).

## Config and secrets posture
- Collector config is typed and validated via `noticiencias.config_manager` (`news_collector/config/settings.py`).
- Secrets are documented as `.env`/GitHub Actions secrets; CI enforces secret scanning in the collector repo.
- Site workflow uses secrets to connect to collector DB; driver defaults to sqlite when secrets are missing.

## Rollout and rollback
- Collector releases: tags trigger changelog update and container artifact build.
- Site releases: merge to `main` deploys directly to GitHub Pages; rollback is via reverting commits.
- Healthcheck tooling exists for collector runtime confidence (`docs/runbooks/healthcheck.md`).

## Findings (logged in ledger)
- F-0004 (S2): Sync workflow falls back to sqlite when secrets are missing, risking drift.
- F-0005 (S3): Feature flags referenced in docs but no flag registry file exists.

## Recommended next steps
1) Enforce required DB secrets for `sync-published` or fail fast to avoid silent drift.
2) Create the flag registry (`config/features.yaml`) or remove the reference from `AGENTS.md`.
