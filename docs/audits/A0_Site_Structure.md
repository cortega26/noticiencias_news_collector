# A0 Structure and Modularity (Site)
Last updated: 2026-01-02

## Scope
- c:\Users\corte\VS Code Projects\noticiencias

## Evidence reviewed
- Repository root layout and tracked directories.

## Findings (logged in ledger)
- F-0011 (S2): `temp-site/` tracked alongside production site.

## Notes
- Primary site structure is standard Jekyll (`_posts`, `_layouts`, `_includes`).
- `temp-site/` contains a parallel site copy and can cause confusion for edits.

## Recommended next steps
1) Remove or archive `temp-site/` outside the repo, or document its purpose clearly.
