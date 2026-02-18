# A2 Quick Scan - Security
Last updated: 2026-01-02

## Scope
- c:\Users\corte\VS Code Projects\noticiencias_news_collector
- c:\Users\corte\VS Code Projects\noticiencias

## Method (quick scan)
- Secret/credential sweep (patterns, `.env` tracking, example configs).
- Authn/authz surface review for admin workflows.
- High-risk defaults in local runtime configs (compose, env).
- Obvious unsafe primitives (unsafe eval, deserialization, SSL bypass).

## Findings (logged in ledger)
- F-0001 (S1) Refinery UI publish actions exposed without auth if UI is reachable.
- F-0002 (S2) GitHub token embedded in clone URL may persist in `.git/config`.
- F-0003 (S3) Default Postgres password in docker-compose.

## Repo notes
### noticiencias_news_collector
- `.env` is ignored by git (`.gitignore` includes `.env`), and no tracked secrets detected in code/docs.
- Refinery actions are triggered directly from Streamlit UI with no authentication guard.

### noticiencias (site)
- No immediate S0/S1 findings from quick scan.
- Secrets appear as placeholders in docs/config backups; no tracked API keys detected.

## Next steps
- Proceed with A6 release/config/change safety.
- If the Refinery UI is ever exposed beyond localhost, prioritize F-0001 before deployment.
