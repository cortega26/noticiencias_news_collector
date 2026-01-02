# Findings Ledger

> Use one ledger for the whole program. Each finding has one “home” audit.
> Other audits may reference the ID but must not duplicate the same finding.

## Severity: S0 Stop-ship | S1 High | S2 Medium | S3 Low

| ID | Severity | Home Audit | Area | Title | Evidence | Impact | Recommendation | Owner | Status | Target Date |
|---|---|---|---|---|---|---|---|---|---|---|
| F-0001 | S1 | A2 | Admin Access | Refinery UI allows publish actions without auth if exposed | `apps/refinery/admin_panel.py:353` | Unauthorized users could trigger publication/PRs using the configured GitHub token if the UI is reachable | Restrict Streamlit to localhost or add auth (reverse proxy, OAuth, or Streamlit auth) before deploying beyond a trusted network | TBD | Closed | 2026-01-02 |
| F-0002 | S2 | A2 | Secrets Handling | GitHub token is embedded in clone URL and may persist in `.git/config` | `apps/refinery/src/services/git_service.py:43` | Token can be written to disk inside temp repos, increasing leak risk via backups or logs | Use credential helpers or `GIT_ASKPASS`, or reset remote URL after clone/push to avoid storing tokens in `.git/config` | TBD | Closed | 2026-01-02 |
| F-0003 | S3 | A2 | Default Credentials | Docker compose uses `password` for Postgres | `docker-compose.yml:23` | Risk of weak credentials if used outside local/dev contexts | Replace with env overrides in docs and include a stronger default or a warning banner | TBD | Closed | 2026-01-02 |
| F-0004 | S2 | A6 | Config Drift | Site sync workflow falls back to sqlite when DB secrets are missing | `noticiencias/.github/workflows/sync-published.yml:39` | Published-article sync can silently write to ephemeral sqlite on the runner, leaving the collector DB out of sync | Require DB secrets for this job or fail fast if they are missing; document expected secrets | TBD | Closed | 2026-01-02 |
| F-0005 | S3 | A6 | Feature Flags | Feature flag file referenced but missing | `AGENTS.md:187` | No defined flag registry for safe rollouts despite documented expectation | Add `config/features.yaml` or remove the documentation; document flag ownership and defaults | TBD | Closed | 2026-01-02 |
| F-0006 | S2 | A1 | Deduplication | Concurrent inserts can bypass content-hash dedupe | `news_collector/storage/database.py:383` + `news_collector/storage/models.py:66` | Duplicate articles with different URLs can be stored during parallel collection runs, skewing scoring and exports | Add a unique constraint or transaction-level lock on `content_hash` (or introduce a canonical URL hash) and handle IntegrityError for content-hash collisions | TBD | Closed | 2026-01-02 |
| F-0007 | S2 | A1 | Publishing | Slug collisions can overwrite existing posts in PR branch | `apps/refinery/main.py:406` | Two same-day articles with the same title slug overwrite each other, leading to data loss in the target repo | Append a short unique suffix when filename already exists or include article ID in filename | TBD | Closed | 2026-01-02 |
| F-0008 | S2 | A0 | Repo Hygiene | Tracked runtime artifacts and exports in repo root | `data/exports/latest_articles.json`, `data/exports/test_export.json`, `temp/source`, `debug_output.txt`, `test_output*.txt` | Repo bloat, stale artifacts, and confusion when reviewing diffs or onboarding | Move generated outputs to ignored paths; keep only minimal fixtures under `tests/fixtures` | TBD | Closed | 2026-01-02 |
| F-0009 | S3 | A4a | Maintainability | Large monolithic modules increase change risk | `news_collector/storage/database.py`, `news_collector/collectors/rss_collector.py`, `main.py`, `news_collector/scoring/basic_scorer.py` | Harder to reason about changes and write focused tests; higher regression risk | Split into smaller modules and add targeted unit tests around critical logic | TBD | Closed | 2026-01-02 |
| F-0010 | S2 | A3 | Data Lineage | Export JSON lacks schema/version metadata | `run_collector.py:445` | Downstream consumers can break silently when fields change | Add `schema_version`, `generated_at`, and export contract reference at the top-level | TBD | Closed | 2026-01-02 |
| F-0011 | S2 | A0 | Repo Hygiene | `temp-site/` tracked alongside production site | `noticiencias/temp-site/*` | Confusing for contributors and increases risk of editing the wrong site copy | Move to a separate archive or untrack; document if it must stay | TBD | Closed | 2026-01-02 |

### Notes
- **Evidence** should be verifiable: file paths, line references, logs, screenshots, test output.
- **Recommendation** should be actionable and scoped.
- Prefer **small PRs** with safe rollout (feature flags, migrations, canaries) where relevant.
