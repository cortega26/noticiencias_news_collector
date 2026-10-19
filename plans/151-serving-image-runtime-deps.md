# Plan 151: The serving image must be able to serve the routes it exposes

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat a4be5e6f..HEAD -- Dockerfile.serving news_collector/serving/api.py news_collector/logic/workflows/published_content.py news_collector/logic/workflows/published_content_utils.py docs/RUNBOOK_LOCAL_DEV.md docs/PIPELINE_CONTRACTS.md deploy/ docker-compose.serving.yml fly-serving.toml tests/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M (includes one operator decision — see Step 1)
- **Risk**: LOW-MED (touching the production image)
- **Depends on**: plan 134 (DONE, merged `a4be5e6f`)
- **Category**: bug (deployed runtime) + tests
- **Planned at**: commit `a4be5e6f`, 2026-10-19

## Why this matters

Plan 134 fixed the *import-surface* half of the deployed-image defect: nothing
under `news_collector/` imports the legacy `apps/` tree any more. The
*other* half is a runtime dependency: `Dockerfile.serving` (python:3.13-slim)
installs no `git` binary, and `news_collector/logic/workflows/published_content.py`
imports GitPython at module level (`import git`), so in the container the three
published-content routes still answer **500** — verified live during plan 134's
review (my own smoke run):

```
$ curl -s -o /dev/null -w '%{http_code}' localhost:8124/v1/admin/content -H 'Authorization: Bearer test'
500        # /v1/admin/analytics → 200 (the fixed one)
$ docker logs … → ImportError: Failed to initialize: Bad git executable.
```

So the image currently reports success on `/healthz` while three of its admin
routes are dead. Whoever operates this surface (the Astro admin panel's Content
page: `apps/admin/src/pages/content.astro` → `api.ts:338,352,358`) hits a 500
with no actionable message. This plan closes that gap — and adds the guard so
the *next* missing runtime dependency is caught by a test rather than by a user.

## Current state

- `Dockerfile.serving` — the whole install surface:

```dockerfile
FROM python:3.13-slim@sha256:70729b46…        # no apt-get step anywhere
ENV NOTICIENCIAS__APP__ENVIRONMENT=production
COPY pyproject.toml README.md LICENSE requirements.lock ./
COPY config.toml ./
COPY news_collector ./news_collector
COPY noticiencias ./noticiencias
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
```

- `news_collector/logic/workflows/published_content.py` — module-level
  `import git`; the module resolves the frontend checkout and (when absent)
  clones it, so it needs both a `git` binary and a usable checkout.
- The three routes: `GET /v1/admin/content` (`serving/api.py:2269-2272`),
  `DELETE /v1/admin/content/{refinery_id}` (`:2442`), `POST /v1/admin/content/bulk-reset` (`:2489-2490`).
- The Astro admin calls them (`apps/admin/src/lib/api.ts:338,352,358`) and the
  Content page is part of the daily review loop; `docs/RUNBOOK_LOCAL_DEV.md`
  says production serving requires `ADMIN_API_KEY`, i.e. these routes are
  expected to be reachable in production.
- Established guard from plan 134:
  `tests/unit/serving/test_serving_import_surface.py` (AST scan + image-shaped
  subprocess proof) — it covers *Python* importability, not binaries.
- `fly-serving.toml` / `docker-compose.serving.yml` build exactly this image.

## Commands you will need

| Purpose          | Command                                                                 | Provenance | Expected on success            |
|------------------|-------------------------------------------------------------------------|------------|--------------------------------|
| Install/baseline | `make bootstrap`                                                        | declared   | exit 0                         |
| Lint / types     | `make lint && make type`                                                 | declared   | exit 0                         |
| Unit suite       | `make test`                                                              | declared   | all pass                       |
| Boundaries       | `make test-boundaries`                                                   | declared   | exit 0                         |
| Contracts        | `make test-contracts`                                                    | declared   | exit 0                         |
| Image build      | `docker build -f Dockerfile.serving -t nc-serving:plan151 .`              | declared   | exit 0                         |
| Image smoke      | `docker run -d --rm -e ADMIN_API_KEY=test -p 8125:8000 nc-serving:plan151` then curl `/healthz`, `/v1/admin/analytics`, `/v1/admin/content` | declared | see Step 3 |
| Ledger           | `make plans-ledger-check`                                                | declared   | `validate_plans_ledger: OK`    |

Provenance: all `declared` (advisor read the files; the plan-134 executor ran the
equivalent build/smoke successfully, so Docker is available on this machine).

## Scope

**In scope**:

- `Dockerfile.serving` (add the runtime dependency the routes need, or add the
  explicit degradation path — per the Step 2 decision)
- `news_collector/serving/api.py` (only if the chosen option is an explicit
  503 / guarded route — keep the change to those three handlers)
- `tests/` — a container-level or in-process guard asserting the chosen status
- `docs/RUNBOOK_LOCAL_DEV.md`, `docs/PIPELINE_CONTRACTS.md` — document the route's
  production behaviour (visibly, not silently)
- `fly-serving.toml` / `docker-compose.serving.yml` — only if the chosen option
  needs a mounted checkout or an extra env var

**Out of scope** (do NOT touch):

- The `published_content.py` module's behaviour beyond what the decision needs.
- The `apps/` boundary (plan 134's guard owns it).
- The published-content *implementation* (git operations, manifest handling).
- `requirements.lock` / `pyproject.toml` — git is a system binary, not a wheel.

## Git workflow

- Branch: `advisor/151-serving-image-runtime-deps`
- Conventional commits, e.g. `fix(serving): make the published-content routes honest in the image (plan 151)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run the `Install` row, `make lint`, `make test`, `make test-boundaries`,
`make test-contracts`, then build the image and reproduce the 500 with the curl
above. Record the observed status codes.

**Verify**: gates exit 0; `/v1/admin/analytics` → 200 and `/v1/admin/content` →
500 (the defect this plan exists to fix).

### Step 1: Decide the route's production contract (operator-dependent)

Answer these from the repo, in this order:

1. Is the Content page (`apps/admin/src/pages/content.astro`) used against the
   **hosted** serving API in production, or only against the local
   `make admin` stack? Evidence: `docs/RUNBOOK_LOCAL_DEV.md`, the deployment
   notes (`spec-oci-hosting-migration.md`, `docs/ops/`), `apps/admin/README` or
   the panel's own docs, and the operator's runbooks.
2. If it is used in production: which frontend checkout should the route read —
   a checkout on the serving host, or a fresh clone per request (needs network +
   token + git)? Evidence: how `resolve_published_content_snapshot` resolves
   `POSTS_DIR`/`TARGET_DIR` and the env vars the image sets.
3. If the repo cannot answer 1 or 2, **STOP and report the question** — this is a
   product decision, not an executor's to invent. Present the two candidate
   answers with their evidence so the operator can pick.

**Verify**: your written answer (or the STOP report) cites the files you read.

### Step 2: Implement the chosen option

- **Option A — the routes must work in production:** add `git` to the image
  (`apt-get update && apt-get install -y --no-install-recommends git && rm -rf
  /var/lib/apt/lists/*`, placed to keep the layer cache useful, with the base
  digest pin kept intact), then make sure the route has a checkout: mount one
  (compose/fly volume) or let it clone (verify the token/network path actually
  works in the container). Keep the image slim: no other apt packages.
- **Option B — the routes are a local-admin feature:** make them fail
  *explicitly* instead of 500 — a guard that detects the missing capability
  (e.g. no `git` binary and no configured checkout) and returns **503** with a
  stable error code and a message naming the requirement, before any `git`
  import is attempted (import the module lazily inside the handler and convert
  the failure). Document in `docs/RUNBOOK_LOCAL_DEV.md` that the Content page
  requires the local stack (or the configured checkout).
- **Option C — the routes are not wanted in the hosting tier at all:** gate them
  behind an existing config flag (find one; do not invent a new knob without the
  operator's word) and return 404/503 in that tier, documented.

Whatever the option: **no route may answer 500 for a missing deployment
capability**, and the surface must say why.

**Verify**: the image builds; the route's status matches the chosen contract;
the response body names the requirement (option B/C) or the route works (option A).

### Step 3: Guard it with a test, not with a container run

Extend the plan-134 guard family with a test that would have caught this: either

- a container-level smoke script wired into the existing image-build job
  (`.github/workflows/ci.yml`'s `build-artifacts` job, or wherever
  `Dockerfile.serving` is built) that calls the three admin routes and asserts
  the contract (200, or the documented non-500), or
- an in-process test that simulates the deployment capability being absent
  (monkeypatch the git-availability probe / point the checkout env at an empty
  dir) and asserts the explicit status, when Option B/C is chosen.

Prefer the container smoke when the build job already exists (it is the only
thing that can see a missing *binary*).

**Verify**: the new guard fails against the pre-change image (prove it once: run
it before adding the fix) and passes after.

### Step 4: Document the deployment contract

Update `docs/RUNBOOK_LOCAL_DEV.md` (the serving section) and, if the route's
semantics changed, `docs/PIPELINE_CONTRACTS.md`'s admin-parity paragraph
("admin parity surface (Phase 4): unpublish + bulk reset …", around `:170-180`).

**Verify**: `make docs-check && make docs-review` exit 0.

## Test plan

- New guard per Step 3 (container smoke preferred; in-process acceptable for
  Option B/C).
- Keep `tests/unit/serving/**` green; the plan-134 AST guard stays untouched.
- Manual evidence: the recorded curl status codes before/after, with the
  container log line for the missing capability (never paste secrets).

**Verify**: `make test && make test-boundaries && make test-contracts` → green;
the smoke records the contract.

## Done criteria

All must hold:

- [ ] `make lint`, `make type`, `make test`, `make test-boundaries`, `make test-contracts` exit 0
- [ ] The chosen contract is implemented and documented; no admin route answers
      500 for a missing capability
- [ ] The new guard fails pre-change and passes post-change (proof recorded)
- [ ] The image builds; the smoke's status codes recorded
- [ ] `make docs-check` exits 0
- [ ] `git diff --name-only main...HEAD` lists only in-scope files
- [ ] `plans/README.md` row 151 updated; `make plans-ledger-check` → OK

## STOP conditions

- Step 1 cannot be answered from the repo → STOP and ask; do not guess the
  production contract.
- Option A requires adding more than `git` (e.g. a `node`/`npx` toolchain to the
  serving image) → STOP and report the actual requirement; that is a deployment
  decision with a size cost.
- The container smoke needs a registry/network access the environment does not
  have → report it; do not fake the smoke.
- Any change would touch `apps/` or re-introduce an `apps.*` import in
  `news_collector/` → STOP (plan 134's guard exists for that).

## Maintenance notes

- The durable lesson from plan 134 + this plan: the serving image's dependency
  surface is Python-wheels + system binaries + mounted data. The import-surface
  test covers the first; this plan's guard must cover the other two.
- Reviewer should scrutinise: base-image digest still pinned (ADR-0002 style),
  no credentials in the image or the smoke commands, and that the route's new
  failure mode is *actionable* (names the missing thing).
- **Deferred:** a general "serving image capability checklist" (each exposed
  route's runtime requirements) is worth writing once a second binary
  dependency appears — not worth a doc no one reads yet.
