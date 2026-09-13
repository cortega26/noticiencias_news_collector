# Phase 2 — Generate four admin response contracts

Prerequisite: Phase 0. Risk: Critical (dependency/CI), High (API contract).
This is a partial delivery of Plan 060 Phase 6, not a replacement for that plan.

## Read first and copy patterns

Read `create_app` in `news_collector/serving/api.py`, the four workflow routes,
`news_collector/contracts/admin.py`, the admin `types.ts`/`api.ts`/`api.test.ts`,
`tests/test_serving_admin_api.py`, and the official OpenAPI links in Phase 0.
Copy the existing injected SQLite-manager pattern and documented
`components["schemas"][...]` alias pattern.

## File scope

| Path | Change |
| --- | --- |
| **New** `scripts/export_admin_openapi.py` | Deterministic schema export/check CLI using real app factory. |
| **New** `apps/admin/openapi.json` | Committed full application OpenAPI document; admin consumes a subset. |
| **New** `apps/admin/src/lib/generated/api.d.ts` | Generated TypeScript declarations. |
| `apps/admin/package.json`, `package-lock.json` | Exact tested `openapi-typescript` dev pin; generation/check scripts. |
| `apps/admin/src/lib/types.ts` | Replace exactly four interfaces with generated type aliases. |
| `apps/admin/src/lib/api.test.ts` | Preserve/test public client behavior as needed. |
| **New** `tests/contracts/test_admin_openapi.py` | Offline export, deterministic bytes, schema behavior and drift tests. |
| `tests/test_serving_admin_api.py` | Extend existing response-shape coverage only where missing. |
| `Makefile`, `.github/workflows/ci.yml`, `docs/ci.md`, `docs/PIPELINE_CONTRACTS.md` | Generation/check entry points, CI gate and contract ownership docs. |
| `plans/060/spec.md`, plan 080 evidence/checklist | Record precise partial progress; keep broader Phase 6 pending. |

Do not change `api.ts` transport, auth, error classes or public response semantics.
Do not add `openapi-fetch`, runtime Zod validation, global TypeScript flags, a
second router inventory, or publication-schema generation in this phase.
If aliases expose a real mismatch, fix only the affected consumer with a precise
type-safe adaptation; list that file in this spec before editing. Do not use
`as any`, `as unknown as`, or `Required<...>` to conceal schema inaccuracies.

## Work package A — Reproducible schema artifact

Implement this new CLI contract (these flags are to be authored):

```bash
.venv/bin/python scripts/export_admin_openapi.py --output apps/admin/openapi.json
.venv/bin/python scripts/export_admin_openapi.py --check apps/admin/openapi.json
```

- Before any project import, enable the established `NEWS_COLLECTOR_TEST_MODE=1`
  isolation convention. Keep this setting local to this schema-only process.
- Create a temporary SQLite `DatabaseManager` and pass it explicitly to
  `create_app(database_manager=manager)`. Call `.openapi()` without entering
  lifespan, starting a server, making requests or starting workflows. Close the
  manager and temporary resources in `finally`/context managers.
- Inspect imported module initialization for other writes. Prove it cannot touch
  production DB/cache/logs; adapt existing test-isolation configuration if needed.
  Do not assume avoiding lifespan also avoids import-time side effects.
- Serialize UTF-8 JSON with sorted keys, two-space indent and final newline.
  Retain the complete schema and all references. Add no timestamp, machine path
  or credentials. Do not filter/sort semantic arrays or alter the API document.
- `--check` generates fresh bytes in memory, compares with the specified artifact
  and exits nonzero if missing/stale. It never rewrites the artifact. Both modes
  return nonzero on generation errors; report useful mismatch context.
- Test that default `get_database_manager()` and recovery/dispatch would raise
  if called. Explicit temporary database creation is allowed; production access
  and schema-only lifespan execution are not.

## Work package B — Aliases with unchanged behavior

Pin the tested stable `openapi-typescript` version in admin devDependencies and
commit the resulting npm lock. Resolve compatibility using Node 24; do not
upgrade Astro/Vitest/Tailwind or rewrite unrelated lock entries intentionally.
Use the local dependency through npm scripts, not an unpinned `npx` download.

Add these npm scripts in `apps/admin`:

```json
{
  "contracts:generate": "openapi-typescript openapi.json --output src/lib/generated/api.d.ts",
  "contracts:check": "openapi-typescript openapi.json --output src/lib/generated/api.d.ts --check"
}
```

Replace the four existing interfaces with aliases to the actual generated names:

```ts
import type { components } from "./generated/api";

export type AdminCollectStarted = components["schemas"]["AdminCollectStarted"];
export type AdminCollectStatus = components["schemas"]["AdminCollectStatus"];
export type AdminPublishStarted = components["schemas"]["AdminPublishStarted"];
export type AdminPublishStatus = components["schemas"]["AdminPublishStatus"];
```

Check the artifact for these identifiers first; FastAPI can distinguish input
and output schemas. Preserve generated nullability, defaults and optionality.
Use response/output schemas if names differ. Do not edit the generated file.
The request's “exactly one of ID/URL” check currently lives in workflow logic;
type generation does not express or replace it.

## Work package C — Drift gate

Add Make targets `admin-contracts-generate` and `admin-contracts-check`.
Generation runs schema export then npm generation; check runs fresh schema
comparison then npm `contracts:check`, propagating each exit code. No implicit
package installation or service startup in these targets. Keep `admin-build`
usable with committed artifacts and no Python/server dependency.

Add a dedicated job to existing `ci.yml`, following its pinned checkout/setup
action conventions. Provision Python 3.13 and the project's locked dependencies,
Node 24 and `npm ci` in `apps/admin`; run `make admin-contracts-check`,
`make admin-test`, and `make admin-build`. Inspect existing trigger/path filters
so changes to contracts, serving routes, exporter, admin or Makefile trigger it.
Do not add this Node-dependent check to backend-only `make verify-ci` in this
pilot. Document the additional required CI job in `docs/ci.md`.

## Acceptance

- **A1:** schema export succeeds without credentials/network/production files;
  explicit temporary SQLite is cleaned, and no lifespan/recovery/dispatch runs.
- **A2:** two fresh exports and two type generations are byte-identical. Backend
  schema changes fail `--check` even when committed schema and TS agree with each
  other. Stale TS alone fails npm `contracts:check`. Missing artifacts fail.
- **A3:** exactly four manual interfaces become generated aliases; admin tests
  and Astro typecheck/build pass without wire or visible behavior changes.
- **A4:** fixture HTTP responses preserve POST 202/409 and status GET 200/404
  for both workflows; unknown run IDs stay 404; no-run status stays inactive;
  queued/running/succeeded/failed/cancelled/interrupted remain representable.
  Preserve 401/403 and both forms of 422 handling in existing client tests.
- **A5:** CI fails a deliberately stale artifact in an isolated test copy; checks
  never repair it. Both artifacts are committed, allowing offline admin builds.

Important existing nuance: validation can produce a list-valued `detail`, while
publication's invalid-request branch raises a string-valued `detail`. Do not
claim this pilot fully models all error envelopes or rewrite error handling to
fit generated types. The target generated contracts are four response models;
existing 409/404 declarations already cover their alternate statuses.

## Verification

```bash
.venv/bin/python -m pytest tests/contracts/test_admin_openapi.py tests/test_serving_admin_api.py --no-cov -q
make admin-contracts-generate
make admin-contracts-check
make admin-test
make admin-build
make lint
make type
make test
make test-contracts
make test-boundaries
make quality
make docs-check
make plans-ledger-check
```

Record fresh-export/type bytes and failure-probe outcomes in
`tests/phase-2-results.md` under this plan. No public frontend was changed, so its
build suite is not a phase requirement. If UI markup/interaction changes become
necessary, update scope and add 375px/1280px browser verification; do not silently
turn a type-only pilot into a UI refactor.

Rollback: revert aliases and corresponding artifacts/tooling/CI together.
No database rollback or production API change should be necessary.
