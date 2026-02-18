# A4a Engineering Quality (Tests, Maintainability, Perf)
Last updated: 2026-01-02

## Scope
- c:\Users\corte\VS Code Projects\noticiencias_news_collector

## Evidence reviewed
- Test suites under `tests/` (unit, e2e, perf markers).
- CI pipeline coverage gates in `c:\Users\corte\VS Code Projects\noticiencias_news_collector\.github\workflows\ci.yml`.
- Large modules identified for maintainability risk.

## Findings (logged in ledger)
- F-0009 (S3): Large monolithic modules increase change risk.

## Test strategy snapshot
- Unit and integration tests live under `tests/`.
- End-to-end tests use `-m e2e` and run in CI.
- Performance tests use `-m perf` and produce reports under `reports/perf`.

## Maintainability hotspots
- `news_collector/storage/database.py` (~50 KB)
- `news_collector/collectors/rss_collector.py` (~48 KB)
- `main.py` (~37 KB)
- `news_collector/scoring/basic_scorer.py` (~35 KB)

## Recommended next steps
1) Decompose the largest modules around core responsibilities (DB ops vs dedupe vs scoring).
2) Add focused unit tests around dedupe, scoring weights, and collector parsing.
