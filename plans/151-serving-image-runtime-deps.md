# Plan 151: The serving image must be able to serve the routes it exposes

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 736ad5f2..HEAD -- Dockerfile.serving news_collector/serving/api.py news_collector/logic/workflows/published_content.py news_collector/logic/workflows/published_content_utils.py docs/RUNBOOK_LOCAL_DEV.md docs/PIPELINE_CONTRACTS.md docs/ci.md tests/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S-M
- **Risk**: LOW
- **Depends on**: plan 134 (DONE, merged `a4be5e6f`); **sequence with plan 138**
  (it owns `docs/ci.md` and `ci.yml` right now)
- **Category**: bug (deployed runtime) + tests
- **Planned at**: commit `736ad5f2`, 2026-10-19

### Decision (2026-10-19) — Option B: fail honestly; do not provision a checkout in the hosting tier

The three published-content routes (`GET /v1/admin/content`,
`DELETE /v1/admin/content/{refinery_id}`, `POST /v1/admin/content/bulk-reset`)
inspect or clone the **frontend repository**. The hosted serving image
(`Dockerfile.serving`) ships neither a `git` binary nor a frontend checkout, and
giving it one would require a mounted volume **plus** a GitHub token in a tier
that is published through a public tunnel. Installing `git` alone would only turn
today's `ImportError` 500 into a different failure (no checkout → clone attempt →
token/network error) while widening the image's attack surface.

So: **the published-content surface is an explicit local-admin capability.** In
the hosting tier it returns **503** with a stable code and a message naming the
missing requirement; in the local stack (`make admin`, git present, checkout
available) it keeps working unchanged. Option A (git + mounted checkout in the
image) stays available if the operator later decides the Content page must work
against hosted serving — that is a deployment decision (volume + token), recorded
as a deferred item below.

## Why this matters

Plan 134 fixed the *import-surface* half of the deployed-image defect: nothing
under `news_collector/` imports the legacy `apps/` tree any more, and
`/v1/admin/analytics` answers 200 in the image. The *runtime* half remains: the
image has no `git`, `published_content.py` imports GitPython at module level, and
the three published-content routes still answer **500** — verified live during
plan 134's review:

```
$ curl -s -o /dev/null -w '%{http_code}' localhost:8124/v1/admin/content -H 'Authorization: Bearer test'
500        # /v1/admin/analytics → 200 (the fixed one)
$ docker logs … → ImportError: Failed to initialize: Bad git executable.
```

A 500 says "we broke"; a 503 with `published_content_unavailable` says "this
deployment does not provide the capability" — which is the truth and is
actionable for whoever reads the admin panel.

## Current state

- `Dockerfile.serving` — the install surface (no apt-get step anywhere):

```dockerfile
FROM python:3.13-slim@sha256:70729b46…
ENV NOTICIENCIAS__APP__ENVIRONMENT=production
COPY pyproject.toml README.md LICENSE requirements.lock ./
COPY config.toml ./
COPY news_collector ./news_collector
COPY noticiencias ./noticiencias
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
```

- `news_collector/logic/workflows/published_content.py` — module-level
  `import git` (GitPython raises `ImportError: Failed to initialize: Bad git
  executable` when the binary is absent), plus checkout resolution/clone helpers.
- The three routes in `news_collector/serving/api.py` import that module **inside**
  the handler body (plan 134's rewiring), so the image boots and `/healthz` is
  200 while those routes fail at request time.
- `apps/admin/src/lib/api.ts:338,352,358` calls them from the Content page.
- Plan 134's guard `tests/unit/serving/test_serving_import_surface.py` covers
  *Python* importability, not system binaries or deployment capabilities.
- `fly-serving.toml` / `docker-compose.serving.yml` build exactly this image.

## Commands you will need

| Purpose          | Command                                                                 | Provenance | Expected on success                    |
|------------------|-------------------------------------------------------------------------|------------|----------------------------------------|
| Install/baseline | `make bootstrap`                                                        | declared   | exit 0                                 |
| Lint / types     | `make lint && make type`                                                 | declared   | exit 0                                 |
| Unit suite       | `make test`                                                              | declared   | all pass                               |
| Boundaries       | `make test-boundaries`                                                   | declared   | exit 0                                 |
| Contracts        | `make test-contracts`                                                    | declared   | exit 0                                 |
| Image build      | `docker build -f Dockerfile.serving -t nc-serving:plan151 .`              | declared   | exit 0                                 |
| Image smoke      | run the image with `ADMIN_API_KEY=test` on port 8125, then curl `/healthz`, `/v1/admin/analytics`, `/v1/admin/content` | declared | 200 / 200 / **503** |
| Ledger           | `make plans-ledger-check`                                                | declared   | `validate_plans_ledger: OK`            |

Provenance: all `declared`. Docker is available on this machine (plan 134 ran the
equivalent build/smoke successfully).

## Scope

**In scope**:

- `news_collector/serving/api.py` — the three published-content handlers only:
  lazy import guarded, capability probe, 503 with a stable code
- `news_collector/logic/workflows/published_content.py` — only if the probe
  belongs there (e.g. an `is_available()` helper); no behaviour change to the
  working path
- `tests/` — a container smoke (or an in-process equivalent if Docker is
  unavailable) asserting analytics 200 / content 503, and a unit test for the
  probe
- `docs/RUNBOOK_LOCAL_DEV.md`, `docs/PIPELINE_CONTRACTS.md` — document that the
  surface is local-admin and what 503 means
- `docs/ci.md` — only if you wire the smoke into the image-build job (that file
  is shared with plan 138; coordinate, or leave the wiring to a follow-up)

**Out of scope** (do NOT touch):

- `Dockerfile.serving` — **do not add `apt-get install git`** and do not add a
  checkout/token (see the decision note).
- Any route other than the three published-content ones.
- The published-content implementation itself (git operations, manifest
  handling).
- `requirements.lock` / `pyproject.toml`.

## Git workflow

- Branch: `advisor/151-serving-capability-503`
- Conventional commits, e.g. `fix(serving): report the published-content capability as unavailable (plan 151)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run the `Install` row, `make lint`, `make test`, `make test-boundaries`,
`make test-contracts`, then build the image and reproduce the 500 with the curl
above. Record the observed status codes.

**Verify**: gates exit 0; `/v1/admin/analytics` → 200 and `/v1/admin/content` →
500.

### Step 1: Make the capability detectable

1. Add a small probe (in `serving/api.py` or as `published_content.is_available()`
   — pick the one that keeps the local path untouched) that answers: is a `git`
   executable available (`shutil.which("git")`) **and** is a frontend checkout
   resolvable from the same configuration the module already uses? Read the
   module's resolution first; do not invent a second source of truth.
2. The probe must be cheap (no network, no clone, no subprocess).

**Verify**: a unit test asserts the probe is true with git + a temp checkout and
false with either missing (monkeypatch `shutil.which` / point the checkout env at
an empty dir; no real network).

### Step 2: Return 503, not 500

3. In the three handlers, before importing `published_content`:
   - if the probe says unavailable → return `JSONResponse(status_code=503,
     content={"detail": ..., "error_code": "published_content_unavailable"})`
     naming the requirement ("this route requires the local admin stack: a git
     binary and a frontend checkout");
   - otherwise import and behave exactly as today.
4. Wrap the import in `except ImportError` as defence-in-depth and convert it to
   the same 503 shape (a missing binary can never surface as a 500).
5. Keep every other admin route untouched.

**Verify**: `.venv/bin/pytest tests/unit/serving tests/test_serving_admin_api.py -q --no-cov` → all pass;
the existing content-route tests (which run locally with git) are unchanged.

### Step 3: Prove it in the image

6. Build the image and run the smoke: `/healthz` → 200, `/v1/admin/analytics` →
   200, `/v1/admin/content` → **503** with `error_code=published_content_unavailable`,
   and the body names the requirement (no stack trace, no secret).
7. If Docker is unavailable: run the probe-level test plus an in-process app with
   the probe forced false (monkeypatch) and assert 503; say explicitly that the
   container check did not run.
8. Add the smoke as a test (a `scripts/` helper or an existing image-check job —
   coordinate with plan 138 before touching `ci.yml`/`docs/ci.md`).

**Verify**: the recorded status codes and the response body shape.

### Step 4: Document the contract

9. `docs/RUNBOOK_LOCAL_DEV.md` (serving section): the published-content surface is
   local-admin; the hosting tier answers 503 by design.
10. `docs/PIPELINE_CONTRACTS.md` (admin parity paragraph): same, plus the code.

**Verify**: `make docs-check && make docs-review` exit 0.

## Test plan

- Probe unit test (available / no git / no checkout).
- Route test: forced-unavailable → 503 with the code (in-process, no container).
- Container smoke (when Docker is available): analytics 200 / content 503.
- Existing serving tests unchanged and green.

**Verify**: `make test && make test-boundaries && make test-contracts` → green.

## Done criteria

All must hold:

- [ ] `make lint`, `make type`, `make test`, `make test-boundaries`, `make test-contracts` exit 0
- [ ] `/v1/admin/content*` answers **503** with `error_code=published_content_unavailable` when the capability is missing (proved in the image or by the in-process equivalent)
- [ ] No admin route answers 500 for a missing capability
- [ ] The local path is unchanged (existing serving tests green)
- [ ] `Dockerfile.serving` untouched (no apt-get, no token, no volume)
- [ ] `make docs-check` exits 0
- [ ] `git diff --name-only main...HEAD` lists only in-scope files
- [ ] `plans/README.md` row 151 updated by the reviewer; `make plans-ledger-check` → OK

## STOP conditions

- The probe cannot be made cheap/deterministic without a second source of truth
  for the checkout path → report the resolution code first; do not duplicate it.
- Making the local path return 503 when a checkout is merely *missing* breaks a
  workflow someone relies on (e.g. the local stack clones on demand) → report;
  the probe must distinguish "cannot work" from "will clone".
- The container smoke requires CI changes that conflict with plan 138 → leave the
  CI wiring out, record it as a follow-up, and keep the local smoke proof.

## Maintenance notes

- The invariant: **a route either works or says why, never 500 for a deployment
  capability**. Any future system dependency of the serving tier belongs in this
  probe (and in the smoke), not in an `ImportError`.
- Reviewer should scrutinise: the 503 body has no internal paths or stack traces,
  and the probe's checkout resolution matches `published_content`'s own logic.
- **Deferred:** Option A (git + mounted checkout + token in the hosting tier) and
  a general "serving image capability checklist". Both are unblocked by an
  operator decision about the Content page in production, not by more code.
