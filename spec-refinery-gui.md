# Spec: Refinery GUI — Phase 2 (professional admin interface)

## Goals

Replace the Streamlit Refinery's editorial surface with a professional,
API-first admin GUI. Phase 1 (`/v1/admin/*` in `news_collector/serving/api.py`,
commit 603e930) provided the typed, authenticated backend surface; this phase
builds the GUI that consumes it — no in-process backend access from the UI.

Success criteria:

1. Every read view in the GUI maps 1:1 to a Phase-1 admin endpoint
   (`/v1/admin/articles`, `/v1/admin/articles/{id}`, `/v1/admin/sources/health`,
   `/v1/admin/analytics`, `/v1/admin/config`); no direct DB/file access.
2. Editorial actions (reject, audit-status) go through the Phase-1 mutation
   endpoints; no workflow logic in the GUI.
3. Auth: user enters `ADMIN_API_KEY` once; GUI stores it in `localStorage`
   (persists across browser restarts), sends it as Bearer on every request,
   fails with a clear 401 screen when the key is wrong/expired. The key may
   also be seeded from `PUBLIC_ADMIN_API_KEY` (`apps/admin/.env`). Under
   `astro dev` with no configured key the gate is skipped entirely
   (`AUTH_BYPASS`), mirroring the backend fail-open in the "development"
   environment; production builds always enforce auth.
4. Professional, responsive, dark-mode editorial UI (Streamlit-grade
   aesthetics); keyboard-first triage: approve/reject/skip hotkeys.
5. Testable without a running backend: unit tests for the API client (mocked
   fetch), component tests with vitest, and an optional live e2e against a
   real serving instance.

## Stack decision

**Astro 7 + Tailwind 4 + TypeScript + Vitest**, as a new app under
`apps/admin/` inside this repo.

Rationale (from the Phase-1 investigation):

- The sibling frontend repo (`../noticiencias`) already runs Astro 7 +
  Tailwind 4 — the toolchain is proven in this product, no new framework
  to learn.
- Streamlit's ceiling (whole-script rerun per interaction, no real hotkeys,
  single-user, no component model) is exactly what this phase removes.
- A standalone app in this repo (not the frontend repo) keeps the public
  site untouched; the GUI is an internal editorial tool.
- Node is available (`node v24`, `npm 11`); npm registry reachable.

No React: the frontend repo uses Astro without React, and the needed
interactivity (triage hotkeys, filters, detail drill-down) fits Astro
client-side scripts + Tailwind. Keeps the toolchain minimal.

## Implementation details

### App layout (`apps/admin/`)

```
apps/admin/
├── astro.config.mjs          # static output, base "/"
├── package.json              # astro, tailwindcss, vitest, typescript
├── tsconfig.json
├── src/
│   ├── lib/
│   │   ├── api.ts            # typed fetch client (Bearer, error mapping)
│   │   ├── types.ts          # mirrors news_collector/contracts/admin.py
│   │   └── api.test.ts       # vitest: mocked fetch
│   ├── components/
│   │   ├── ArticleCard.astro # triage card: score, why_ranked, actions
│   │   ├── ScoreBar.astro    # component breakdown bar
│   │   ├── AuthGate.astro    # ADMIN_API_KEY entry + localStorage (dev-bypassable)
│   │   ├── SourceHealthTable.astro
│   │   ├── AnalyticsView.astro
│   │   └── ConfigView.astro
│   ├── layouts/
│   │   └── AdminLayout.astro # sidebar nav + dark theme
│   ├── pages/
│   │   ├── index.astro       # → redirect to /triage
│   │   ├── triage.astro      # curation desk (hotkeys)
│   │   ├── article/[id].astro
│   │   ├── sources.astro
│   │   ├── analytics.astro
│   │   └── config.astro
│   └── styles/global.css     # Tailwind v4 @import
```

### API client (`src/lib/api.ts`)

- `getToken()/setToken()/clearToken()` — localStorage `refinery_admin_token`,
  falling back to the `PUBLIC_ADMIN_API_KEY` env var. `AUTH_BYPASS` (dev-only,
  no key configured) short-circuits `getToken()` to `null`.
- `apiFetch<T>(path, init)` — attaches Bearer, maps HTTP errors:
  401/403 → `AuthError` (UI shows re-auth), 404 → `NotFoundError`,
  422 → `ValidationError`, network → `NetworkError`.
- Typed wrappers: `listArticles(status, cursor)`, `getArticle(id)`,
  `getSourceHealth()`, `getAnalytics()`, `getConfig()`, `rejectArticle(id,
  reason)`, `updateAuditStatus(id, status, reason)`.
- Types mirror the Pydantic contracts field-for-field (single source of
  truth note: Phase-1 contract tests guard the backend; the GUI types are
  validated at runtime by the API responses).

### Triage desk (`/triage`)

- Left: queue list (status filter pills: pending/publishing/rejected/
  completed; cursor pagination "load more").
- Right: selected article detail + action bar.
- Hotkeys (keyboard-first, per `docs/strategic_features.md` "Flash-Triage"):
  - `j`/`k` — next/previous article
  - `r` — reject (with optional reason prompt)
  - `a` — audit-status pass
  - `f` — audit-status fail
  - `o` — open original URL in new tab
- Optimistic UI: action fires, card updates status on success, error toast
  on failure.

### Views

- `/article/[id]` — full detail: content, score components, why_ranked,
  publication state, audit state, latest ScoreLog.
- `/sources` — `AdminSourceHealthEnvelope` table (feed/pipeline/content OK,
  save ratio, operational state).
- `/analytics` — stats, source performance, score distribution, top
  sources.
- `/config` — sanitized snapshot (environment, github URLs, ollama models,
  scoring weights).

### Auth flow

- `AuthGate.astro` wraps all pages: no resolvable token → full-screen token
  entry. Skipped when `AUTH_BYPASS` is true (`astro dev`, no key configured).
- Token lives in `localStorage` (persists across browser restarts); may be
  seeded from `PUBLIC_ADMIN_API_KEY`. Internal single-operator tool.
- 401 from any request → clear token, show re-auth screen.

### Tests

- `src/lib/api.test.ts` — vitest with a stubbed `fetch`: success,
  401→AuthError, 404→NotFoundError, 422→ValidationError, network error;
  Bearer header attached; token persistence helpers.
- `tests/e2e_admin_gui/` (optional, `ADMIN_GUI_E2E=1`) — Playwright against
  a real serving instance: token entry → triage loads → reject action
  reflects in queue. Runs only when the flag is set (no CI dependency).
- Backend contract tests from Phase 1 remain the source of truth for the
  API; the GUI consumes them.

### Files to change

1. `apps/admin/**` — new app (all files above).
2. `Makefile` — `admin-install`, `admin-dev`, `admin-build`, `admin-test`
   targets (isolated, not in the baseline `test` chain).
3. `docs/PIPELINE_CONTRACTS.md` — note the GUI client as a consumer of the
   admin surface.
4. `spec-refinery-gui.md` + `todo-refinery-gui.md` — this file + todo.

### Streamlit → Astro parity (addendum, 2026-08-29)

- **Refine & Publish** — the Streamlit "Operaciones del Pipeline" publish
  action (pick a scored candidate → run the Refinery → open a PR) is now in
  the Astro GUI: `POST /v1/admin/publish` + `PublicationRunWorkflow`
  (Plan 060 / Phase 4c, `plans/060/phase-4c-publication-run-workflow/`),
  surfaced on `/triage`: a "publishable" filter pill (first and default —
  the export shortlist minus anything in flight / deployed) with a per-card
  "Refine & publish" button, plus a "Publish from URL" box.
- Still Streamlit-only (minor, separate follow-up): the "Settings & Logs"
  system-logs viewer and the "Reinicio de Fábrica" factory reset.

### Explicitly out of scope (documented)

- Migration/removal of the Streamlit app (`apps/refinery/`) — kept working
  until the GUI reaches feature parity; removal is a separate step.
- Image queue, prompt lab, live CMS editing, source manager writes — the
  Phase-1 API surface does not expose them; they are Phase-3 candidates.
- Deployment automation (Fly/static hosting) — local `astro dev`/`build`
  first; hosting decision after the GUI is accepted.

## Cross-origin note (Phase 2 addendum)

The GUI is a separate static app; the serving API must answer browser
requests from its origin. `create_app` adds `CORSMiddleware` with an
explicit allowlist (`ADMIN_CORS_ORIGINS` env var, comma-separated; default
`http://localhost:4321,http://localhost:4322` for `astro dev`/`preview`),
`allow_credentials=False` (Bearer header auth, no cookies),
`allow_methods=["GET","POST","PUT","DELETE"]`, `allow_headers=["Authorization",
"Content-Type"]`. Regression tests assert the preflight/actual responses
carry the expected CORS headers for an allowlisted origin and no
`Access-Control-Allow-Origin` for a non-allowlisted one.

### Local dev: same-origin via proxy (addendum)

CORS is the contract for a **built/hosted** GUI. For local `astro dev`,
`astro.config.mjs` also declares a Vite `server.proxy` that forwards
`/v1/*` to `ADMIN_API_TARGET` (default `http://localhost:8000`), so the
browser sees one origin and no `PUBLIC_ADMIN_API_BASE` / CORS setup is
needed. `make admin` runs the serving API and the GUI together (Ctrl+C
stops both); `make serve` / `make admin-dev` run them separately. The proxy
is dev-only — `astro preview` and a served `dist/` still rely on CORS +
`PUBLIC_ADMIN_API_BASE` (see `apps/admin/.env.example`).

## Verification

1. `make admin-install && make admin-test` — vitest green (client unit).
2. `make admin-build` — Astro build succeeds with type-check.
3. Manual: `make admin-dev` + serving API running → token entry, triage
   loads seeded data, hotkeys work, reject reflects in queue.
4. `make lint && make type && make test` — backend untouched, still green.
5. Optional live e2e: `ADMIN_GUI_E2E=1 npx playwright test`.

Change class: new app (no backend boundary change) → Medium risk; the
backend gates must stay green as regression proof.
