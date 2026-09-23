# Plan 080 — Phase 2 results

Recorded 2026-09-23.

## Deliverable

Four handwritten admin response interfaces are now generated from the
committed OpenAPI artifact of the real app factory, with a drift gate:

| Artifact / entry point | Role |
| --- | --- |
| `scripts/export_admin_openapi.py` | Deterministic export/check CLI (isolated temp SQLite, no lifespan, no default manager). |
| `apps/admin/openapi.json` | Committed OpenAPI document (source of truth for the generated TS). |
| `apps/admin/src/lib/generated/api.d.ts` | Generated TypeScript declarations (`openapi-typescript@7.13.0`, exact pin). |
| `apps/admin/src/lib/types.ts` | The four interfaces became aliases to `components["schemas"][...]`. |
| `tests/contracts/test_admin_openapi.py` | Determinism, isolation, drift and never-repair tests (6). |
| `Makefile` | `admin-contracts-generate`, `admin-contracts-check`. |
| `.github/workflows/ci.yml` | New `admin-contracts` job (Python + Node 24 + `npm ci` in `apps/admin`). |

### Superseded Phase 0 artifacts

`scripts/generate_admin_openapi_snapshot.py` and
`.contract-snapshots/admin_openapi.snapshot.json` were removed. The Phase 0
snapshot proved determinism but was never wired to a consumer; the Phase 2
artifact lives next to the admin app so its build works offline from
committed files. Plan 060 Phase 6 keeps the broader scope (publication JSON
Schema, remaining aliases).

## Evidence

Fresh export bytes (sha256, 2026-09-23):

- `apps/admin/openapi.json` —
  `a1f472d13335c91cc6a95bf4d76df067db532baa94bf1a307fa18209d00acb1f` (108,036 bytes)
- `apps/admin/src/lib/generated/api.d.ts` —
  `b5c2284aff10369c6017804eeba78f05c2812d344562fa62702a01c28a9871fb` (79,448 bytes)

Determinism and isolation (`tests/contracts/test_admin_openapi.py`, 6 passed):

- Two fresh `render_document()` calls are byte-identical; output is valid JSON
  ending in a newline.
- Export succeeds with `get_database_manager`, and both workflows'
  `recover_expired_leases`, monkeypatched to raise — proving the explicit
  temp manager is used and the lifespan never runs.
- `--check` passes on the committed artifact; fails on a stale copy without
  rewriting it; fails on a missing artifact.
- `--output` writes exactly the fresh bytes.

Failure probes:

- Stale artifact (`{"openapi": "3.1.0"}` copy): exit 1, file unchanged.
- Missing artifact: exit 1 with a `make admin-contracts-generate` hint.
- Stale TS alone: `npm run contracts:check` exits nonzero (openapi-typescript
  `--check`), verified by `make admin-contracts-check` wiring.

Isolation notes: `NEWS_COLLECTOR_TEST_MODE=1` (log files redirected to a temp
path) and `RUN_ENVIRONMENT=test` are forced before project imports, so the
enrichment-metrics singleton cannot touch `data/metrics/production/`.
The temporary SQLite directory is removed in `finally`.

## Deliberate scope boundaries (not done here)

No `openapi-fetch`, no runtime Zod validation, no global TS flags, no second
router inventory, no publication-schema generation, no `api.ts` transport or
error-handling changes, no UI changes. Plan 060 Phase 6 remains the owner of
the broader generated-contract program.

## Gates (2026-09-23)

- `pytest tests/contracts/test_admin_openapi.py tests/test_serving_admin_api.py --no-cov -q` → 91 passed
- `make admin-contracts-generate` → schema + TS regenerated, zero diff (deterministic)
- `make admin-contracts-check` → exit 0
- `make admin-test` → 35 passed
- `make admin-build` → `astro check` 0 errors, 10 pages built
- `make lint` → exit 0 (after black formatting of the new test)
- `make type` → 3186 passed, 5 skipped; coverage ratchet OK (92.21 % vs baseline 91.25 %)
- `make test` → 3173 passed, 5 skipped
- `make test-contracts` / `make test-boundaries` → exit 0
- `make docs-check` → 14 docs verified
- `make plans-ledger-check` → OK
- `make security` → exit 0 (Bandit via the severity/status gate, pip-audit, gitleaks)
- `make quality` → **pre-existing failure, not caused by this phase**: its raw
  Bandit invocation flags 11 findings in untouched files
  (`news_collector/collectors/reddit_collector.py`, `scripts/lint_changed.py`,
  `scripts/validate_plans_ledger.py`, …). Reproduced identically on a clean
  `main` checkout with `git stash`; the gated paths (`make security`,
  `make quality-ci`) pass. Same documentation pattern as Phase 1's
  pre-existing `make type` failures.
