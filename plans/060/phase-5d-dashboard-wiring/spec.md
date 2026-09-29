# Plan 060 / Phase 5d — Dashboard health wiring (frontend)

> **Executor instructions**: This phase edits the **frontend repository**
> (`../noticiencias`); the plan artifacts live here. Follow the spec step by
> step, run every verification command in the frontend repo, and confirm the
> expected result before moving on. When done, annotate `plans/060/todo.md`
> Phase 5 item 5 as complete (5c backend half is `70d7137`) and validate the
> plans ledger.
>
> **Drift check (run first, in `../noticiencias`)**:
> `git diff --stat 14d59f4..HEAD -- scripts/generate-metrics.js src/pages/admin/dashboard.astro tests/generate-metrics.test.ts .github/workflows/generate-metrics.yml data/metrics/pipeline-metrics.json scripts/check-contract-sync.js scripts/utils/hero-placeholders.js`
> On any in-scope drift, re-verify the "Current state" references; on a
> mismatch treat it as a STOP.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW-MED (static dashboard data + bot workflow; page falls back to
  `unknown` when evidence is absent)
- **Depends on**: Phase 5c (backend `GET /v1/admin/dashboard/health`,
  backend `70d7137`); Phase 1 (dashboard `unknown` placeholders).
- **Category**: observability (plan 060 Phase 5 item 5, frontend half)
- **Planned at**: frontend `14d59f4`, backend `70d7137`, 2026-09-25

## Why this phase exists

Plan 060 Phase 5 item 5:

> Drive dashboard schema, validation, hero/image, callback, and publication
> health from real attempt/event/check records. Missing evidence is `unknown`,
> not pass.

Phase 5c landed the backend evidence read. The frontend dashboard
(`src/pages/admin/dashboard.astro`) is a static CI-built page that currently
derives three of five checks from `data/metrics/pipeline-metrics.json` and
hard-codes the other two as `unknown` (phase 1). This phase drives every
check from real records and adds the two backend-evidence checks:

| check | real record |
|---|---|
| Schema Contract | `check-contract-sync.js --snapshot` against the committed snapshot |
| Campos editoriales v2 | content frontmatter (already computed) |
| Imágenes hero | `collectHeroImageDiagnostics()` over the posts |
| Derivativos de imagen | derivatives manifest (already computed) |
| Linting | lint result recorded by the metrics workflow |
| Callbacks | backend `GET /v1/admin/dashboard/health` → `callbacks` |
| Publicación | backend `GET /v1/admin/dashboard/health` → `publication` |
| Validación (Content Guard) | backend `GET /v1/admin/dashboard/health` → `validation` |

Any check whose record is absent stays `unknown` — never `pass`.

## Current state (verified at frontend `14d59f4`)

- `scripts/generate-metrics.js:33-190` — sync collectors (`content`,
  `pipeline`, `images`); `main():224`; no `health` section; no network.
- `tests/generate-metrics.test.ts` — runs the script via `execFileSync` with
  `METRICS_ROOT` fixture trees; asserts the no-churn byte-identical contract.
- `src/pages/admin/dashboard.astro:84-121` — five `healthChecks`; two
  hard-coded `unknown` (hero images, linting), the rest derived from metrics.
- `src/components/ds/organisms/DashboardHealthList.astro` — status union
  already `pass | fail | warning | unknown` (fail styling exists).
- `scripts/check-contract-sync.js` — supports
  `--snapshot <snapshot.json> <config.ts>` (standalone; no backend checkout);
  snapshot committed at `.contract-snapshots/frontend_schema.snapshot.json`.
- `scripts/utils/hero-placeholders.js:102` —
  `collectHeroImageDiagnostics({ repoRoot })` → `{ filesCount, errors }`
  (missing image, missing alt, missing local asset, forbidden unallowlisted
  placeholder).
- `.github/workflows/generate-metrics.yml:32-33` — daily metrics job, then a
  bot PR (`ci/metrics-*`, auto-landed when Content Guard passes). It already
  exposes `BACKEND_WEBHOOK_URL`/`BACKEND_WEBHOOK_TOKEN` in the failure step.
- Backend envelope (5c): `{generated_at, publication, callbacks, validation}`
  where each area is `{status, evidence: present|none, detail, measured_at,
  oldest_pending_age_seconds, counts}`; `evidence="none"` is the unknown
  signal.
- Baselines (frontend): `npm run test:audit` (record the count at Step 0);
  `npm run lint`.

## Scope

**In scope** (all in `../noticiencias`):

- `scripts/generate-metrics.js` — new `health` section:
  - `schema` via `spawnSync` of `check-contract-sync.js --snapshot`
    (`unknown` when snapshot/config missing or the script cannot run);
  - `hero_images` via `collectHeroImageDiagnostics({ repoRoot: REPO_ROOT })`
    (`unknown` when there are no posts);
  - `editorial` and `derivatives` promoted from the existing computations;
  - `lint` read from `process.env.CHECK_RESULTS_PATH` (`unknown` when unset);
  - `callbacks` + `publication` from `BACKEND_ADMIN_URL` +
    `BACKEND_ADMIN_TOKEN` when both are set, else `unknown`.
- `src/pages/admin/dashboard.astro` — `healthChecks` built from
  `metrics.health.*` with `unknown` fallbacks; adds Callbacks and Publicación
  rows; no status is inferred from another metric.
- `.github/workflows/generate-metrics.yml` — record the lint check result to
  `$RUNNER_TEMP/check-results.json` (`continue-on-error: true`, so a lint
  failure is *shown* as `fail`, not swallowed), pass `CHECK_RESULTS_PATH` and
  the `BACKEND_ADMIN_URL`/`BACKEND_ADMIN_TOKEN` secrets to the generator.
- Tests `tests/generate-metrics.test.ts` — health section, every unknown
  path, hero pass/warning, artifact-driven lint, backend fetch success and
  failure via a local HTTP server, no-churn preserved.
- `data/metrics/pipeline-metrics.json` — regenerated once and committed so
  the deployed dashboard shows real values before the next bot run.
- `.contract-snapshots/frontend_schema.snapshot.json` — regenerated. The new
  schema check surfaced that the committed snapshot predates the Wave 3
  accountability fields (14 parity errors); `npm run check:contract-sync`
  confirms live parity with the backend schema, so the snapshot is refreshed
  from that authority (`npm run sync:contract-snapshot`).

**Out of scope**:

- Backend changes (5c is landed).
- `apps/admin` (backend repo) and the live API admin app.
- New CI jobs or moving the daily schedule; only the existing metrics job is
  extended.
- Frontend visual redesign; the health list component already renders
  `fail`.

## Design

### `health` section shape

```json
"health": {
  "schema":      {"status": "pass|fail|unknown", "detail": "..."},
  "editorial":   {"status": "pass|warning|unknown", "detail": "..."},
  "hero_images": {"status": "pass|warning|unknown", "detail": "...", "errors": 0},
  "derivatives": {"status": "pass|warning|unknown", "detail": "..."},
  "lint":        {"status": "pass|fail|unknown", "detail": "..."},
  "callbacks":   {"status": "pass|warning|fail|unknown", "evidence": "present|none", "detail": "...", "counts": {...}},
  "publication": {"status": "pass|warning|fail|unknown", "evidence": "present|none", "detail": "...", "counts": {...}},
  "validation":  {"status": "pass|warning|fail|unknown", "evidence": "present|none", "detail": "...", "counts": {...}}
}
```

Backend sections keep `evidence`; frontend sections are `unknown` with no
local record. `measured_at`/ages are deliberately **not** copied into the
committed metrics: relative ages change every run and would make the daily
bot open a timestamp-only PR (the no-churn contract in
`tests/generate-metrics.test.ts`). Counts are stable unless records change.

### Status rules

- **schema**: snapshot check exit 0 → `pass`; exit 1 → `fail` (detail carries
  the checker's stderr tail, bounded); any other/spawn failure or missing
  files → `unknown`.
- **editorial**: no v2 posts → `unknown`; any editorial gap → `warning`;
  otherwise `pass` (same rule the dashboard used inline).
- **hero_images**: no posts → `unknown`; diagnostics errors > 0 → `warning`
  (detail: count + first error, bounded); otherwise `pass`.
- **derivatives**: no manifest/zero derivatives → `unknown` (a missing
  manifest is missing evidence, not a failure); > 0 → `pass`.
  `missing_derivatives > 0` (when the manifest reports it) → `warning`.
- **lint**: artifact `{lint: {status: 'pass'|'fail'}}` → mapped; missing
  artifact or unknown value → `unknown`.
- **callbacks**/**publication**: 5c envelope section mapped 1:1 (trimmed to
  `status`, `evidence`, `detail`, `counts`); absent config, non-200, network
  error, timeout (8s), or malformed body → `unknown` with a bounded reason.

### Backend fetch

`fetch(BACKEND_ADMIN_URL, { headers: { Authorization: 'Bearer …' },
signal: AbortSignal.timeout(8000) })`. `BACKEND_ADMIN_URL` is the full
endpoint URL (e.g. `https://…/v1/admin/dashboard/health`), matching the
existing explicit-URL convention of `BACKEND_WEBHOOK_URL`. Secrets must be
added to the frontend repo; until then both checks are `unknown`, which is
the honest state.

### No-churn

`preserveTimestampsWhenUnchanged` still compares the full report minus
`generated_at` keys. All offline sections are deterministic; the backend
sections only change when backend records change (legitimate churn). `now`
is not embedded in any health value.

## Test plan

- `tests/generate-metrics.test.ts` (subprocess + `METRICS_ROOT`):
  - health section exists; with no snapshot/artifact/backend env, `schema`,
    `lint`, `callbacks`, `publication` are `unknown`.
  - hero images: fixture posts with image+alt → `pass`; a post missing
    `image` → `warning` and `errors >= 1`; empty posts dir → `unknown`.
  - lint artifact: temp JSON via `CHECK_RESULTS_PATH` maps `pass` and `fail`.
  - backend: local `http.createServer` returning a 5c-shaped body maps
    statuses/counts; connection-refused URL (unused port) → `unknown`.
  - consecutive no-op runs stay byte-identical (existing tests, now with the
    health section).
- `npm run test:audit` (full vitest) green.
- `npm run lint`, `npm run build`, `npm run test:dist`, and
  `npm run check:doc-drift` green.
- Dashboard sanity: the page's `healthChecks` array references only
  `metrics.health.*` plus `unknown` fallbacks (grep-level assertion in the
  spec review; astro check covers types).

## Steps

### Step 0: Baseline + drift

In the frontend repo: record `npm run test:audit -t` count baseline; STOP on
drift/non-green.

### Step 1: `generate-metrics.js` health section + tests

Implement the collectors and wire `main()` async; extend the test file.

### Step 2: Dashboard wiring

`dashboard.astro` healthChecks from `metrics.health`; add Callbacks and
Publicación rows.

### Step 3: Workflow + committed metrics

Record lint evidence + backend env in `generate-metrics.yml`; run
`npm run generate:metrics`; commit the refreshed metrics.

### Step 4: Gates + docs

`npm run lint && npm run test:audit && npm run build && npm run test:dist &&
npm run check:doc-drift`; annotate `plans/060/todo.md`; ledger.

## Done criteria (machine-checkable)

- [ ] Every dashboard check reads a real record or falls back to `unknown`;
      no check infers a status from a different metric (test + review)
- [ ] Generation with no snapshot/artifact/backend env yields `unknown` for
      schema/lint/callbacks/publication (test)
- [ ] Hero-image health reflects real diagnostics (pass/warning/unknown
      tests)
- [ ] Lint artifact maps pass/fail, missing artifact yields `unknown` (test)
- [ ] Backend success and failure paths are tested (local HTTP fixture +
      unreachable URL)
- [ ] No-churn contract still holds byte-for-byte (existing tests)
- [ ] Frontend gates green: `npm run lint`, `npm run test:audit`,
      `npm run build`, `npm run test:dist`, `npm run check:doc-drift`
- [ ] `plans/060/todo.md` item 5 checked with evidence; ledger OK
- [ ] Frontend diff only in-scope files

## STOP conditions

- Drift/baseline not clean in either repo.
- A check cannot be derived from a real record without changing the content
  schema or another frontend system's contract (report and leave `unknown`).
- The metrics file cannot stay deterministic offline (no-churn test fails).
- The workflow needs a new secret beyond `BACKEND_ADMIN_URL` /
  `BACKEND_ADMIN_TOKEN` (adding GitHub secrets is an operator action, not a
  code change — use fallback `unknown` until configured).

## Git workflow

- Frontend branch: `advisor/060-phase-5d-dashboard-wiring` (off `main`).
- Frontend commit: `feat(dashboard): drive pipeline health from measured records`.
- Do NOT push/PR unless instructed.
