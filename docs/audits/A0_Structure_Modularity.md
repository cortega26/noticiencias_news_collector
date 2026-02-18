# A0 Structure and Modularity (Lite)
Last updated: 2026-01-02

## Scope
- c:\Users\corte\VS Code Projects\noticiencias_news_collector

## Evidence reviewed
- Repository root layout (top-level folders and tracked artifacts).
- Module boundaries: `news_collector/`, `apps/refinery/`, `noticiencias/`.

## Findings (logged in ledger)
- F-0008 (S2): Tracked runtime artifacts and exports in repo root.

## Notes
- Core domain code is in `news_collector/` with a clear separation from `apps/refinery/`.
- Configuration tooling is centralized under `noticiencias/` with a compatibility shim in `core/`.
- `temp/` is tracked and contains a cloned tree, which blurs runtime output vs source of truth.

## Recommended next steps
1) Remove runtime artifacts from source control and move fixtures under `tests/fixtures`.
2) Keep `temp/` output untracked and regenerate when needed.
