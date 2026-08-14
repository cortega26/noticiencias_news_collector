# Todo: Refinery GUI — Phase 2 (professional admin interface)

Status: `[ ]` pending · `[x]` done · `[~]` in progress

## Scaffold

- [x] `apps/admin/` — Astro 7 + Tailwind 4 + TypeScript app scaffold
- [x] `Makefile` targets: `admin-install`, `admin-dev`, `admin-build`, `admin-test`

## Core client

- [x] `src/lib/types.ts` — mirror Phase-1 admin contracts
- [x] `src/lib/api.ts` — token helpers + typed fetch (error mapping)
- [x] `src/lib/api.test.ts` — vitest mocked-fetch suite (12 tests, green)

## Layout & theme

- [x] `AdminLayout.astro` — sidebar nav + dark editorial theme
- [x] `global.css` — Tailwind v4 import + design tokens

## Views

- [x] `AuthGate.astro` — token entry, sessionStorage, 401 re-auth (no reload loop)
- [x] `/triage` — queue + detail + hotkeys (j/k/r/a/f/o) + status filter pills
- [x] `/article?id=` — full detail (static-friendly query param route)
- [x] `/sources` — source health table
- [x] `/analytics` — analytics read model
- [x] `/config` — sanitized config

## Backend support (surfaced by the live chain)

- [x] Contract: `score_components` allows `Optional[float]` (real data has nulls)
- [x] CORS: `CORSMiddleware` with `ADMIN_CORS_ORIGINS` allowlist + 3 tests
- [x] Regression: null-component admin payload test

## Quality

- [x] `make admin-test` green (12 vitest)
- [x] `make admin-build` green (0 errors / 0 warnings, 6 pages)
- [x] Playwright live e2e: 7/7 PASS against real serving API + preview build
- [x] `make lint && make type && make test` green (backend 1895 passed)
- [x] Docs: `docs/PIPELINE_CONTRACTS.md` + `.env.example` (ADMIN_CORS_ORIGINS)
- [x] Commit + push
