# Plan 134: The serving image must contain everything the serving API imports

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 1ff6926..HEAD -- news_collector/serving/ apps/refinery/analytics_read_model.py apps/refinery/bulk_helper.py apps/refinery/published_content.py apps/refinery/main.py apps/refinery/admin_panel.py Dockerfile.serving tests/ pyproject.toml`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug (deployed-image correctness) + tech-debt (layering)
- **Planned at**: commit `1ff6926`, 2026-10-18

## Why this matters

`news_collector/serving/api.py` imports three modules from `apps.refinery` inside
endpoint bodies. The deployed serving image (`Dockerfile.serving`, used by Fly
`noticiencias-serve` and `docker-compose.serving.yml`) copies only
`news_collector/` and `noticiencias/` — no `apps/` — and `pyproject.toml`'s
`packages.find` excludes it. The imports are function-local, so the app boots and
`/healthz` returns 200 (which is exactly what plan 130's container smoke checked),
but in production those four endpoints raise `ModuleNotFoundError` → HTTP 500 as
soon as `ADMIN_API_KEY` is set (production requires it, per
`docs/RUNBOOK_LOCAL_DEV.md:61`). The affected routes are used by the Astro admin
today (`apps/admin/src/lib/api.ts:220,338,352,358`). Architecturally this is also
a layering inversion: `docs/ARCHITECTURE.md:22-23` classifies `apps/refinery/` as
the legacy Streamlit UI, and production code must not depend on it.

## Current state

- `Dockerfile.serving` (current COPY list):

```dockerfile
COPY pyproject.toml README.md LICENSE requirements.lock ./
COPY config.toml ./
COPY news_collector ./news_collector
COPY noticiencias ./noticiencias
```

- `pyproject.toml:68-69`:

```toml
[tool.setuptools.packages.find]
include = ["news_collector*", "noticiencias*", "scripts*"]
```

- `news_collector/serving/api.py` — the four deferred imports:
  - `:1605` `from apps.refinery.analytics_read_model import build_analytics_read_model`
  - `:2272` `from apps.refinery.published_content import resolve_published_content_snapshot`
  - `:2442` and `:2490` `from apps.refinery.published_content import (...)`
  - `:2489` `from apps.refinery.bulk_helper import run_bulk`
- Importers of the three modules (verified by grep, excluding the legacy venv):
  `news_collector/serving/api.py` (above), `apps/refinery/main.py:16`,
  `apps/refinery/admin_panel.py:60-62,951`, and the docstring in
  `apps/refinery/bulk_helper.py:15`. `news_collector/logic/workflows/published_content_utils.py:14`
  mentions `apps.refinery.published_content` in a comment only.
- The three modules are **UI-free**: `analytics_read_model.py` imports only
  `typing`; `bulk_helper.py` only `dataclasses`/`typing`; `published_content.py`
  imports `git`, `requests`, and `news_collector.*` (`GitHubPublisher`,
  `news_collector.contracts`, `news_collector.logic.workflows.published_content_utils`).

Precedents to follow (do not invent a new package — LAW-B9):

- `news_collector/serving/dashboard_health.py` is already a serving-side read
  model → `analytics_read_model.py` belongs beside it.
- `news_collector/logic/workflows/published_content_utils.py` already exists →
  `published_content.py` belongs beside it.
- `bulk_helper.py` is a dispatch-side helper used by the API → keep it beside
  the API surface it serves.

## Commands you will need

| Purpose            | Command                                                             | Provenance | Expected on success          |
|--------------------|---------------------------------------------------------------------|------------|------------------------------|
| Install/baseline   | `make bootstrap`                                                    | declared   | exit 0                       |
| Lint               | `make lint`                                                         | declared   | exit 0                       |
| Types + coverage   | `make type`                                                         | declared   | exit 0                       |
| Unit suite         | `make test`                                                         | declared   | all pass                     |
| Boundaries         | `make test-boundaries`                                              | declared   | exit 0                       |
| Contracts          | `make test-contracts`                                               | declared   | exit 0                       |
| Import-surface fix | `grep -rn "apps.refinery" news_collector/ \| grep -v Binary`         | declared   | no matches after the change  |
| Container build    | `docker build -f Dockerfile.serving -t nc-serving:plan134 .`         | declared   | build succeeds               |
| Container smoke    | `docker run --rm -e ADMIN_API_KEY=test -p 8123:8000 nc-serving:plan134` then `curl -s -o /dev/null -w "%{http_code}" localhost:8123/v1/admin/analytics -H "Authorization: Bearer test"` | declared | `200` (not 500) |
| Ledger             | `make plans-ledger-check`                                           | declared   | `validate_plans_ledger: OK`  |

Provenance: all `declared`. Docker may be unavailable in the executor's
environment — if `docker` is missing, still do the in-JVM proof in Step 4 and say
so explicitly in the ledger row (do not claim the container check ran).

## Scope

**In scope**:

- New files: `news_collector/serving/analytics_read_model.py`,
  `news_collector/serving/bulk_helper.py`,
  `news_collector/logic/workflows/published_content.py` (moved verbatim from
  `apps/refinery/`)
- `news_collector/serving/api.py` (import lines only)
- `apps/refinery/main.py`, `apps/refinery/admin_panel.py` (import updates)
- `apps/refinery/{analytics_read_model,bulk_helper,published_content}.py`
  (deleted, or kept as thin re-export shims — see Step 2 for the rule)
- `tests/` — import-surface test
- `Makefile` (only if the container smoke needs a target — optional)

**Out of scope** (do NOT touch):

- `Dockerfile.serving`'s COPY list: do **not** add `COPY apps` — that would ship
  the legacy UI source into production and keep the layering inversion.
- API behaviour, response shapes, or the OpenAPI artifact.
- `apps/refinery/admin_panel.py` beyond its import lines.
- `pyproject.toml`'s `packages.find` (the moved modules are already inside
  `news_collector*`).

## Git workflow

- Branch: `advisor/134-serving-image-import-surface`
- Conventional commits, e.g. `refactor(serving): move legacy UI helpers behind the API boundary (plan 134)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run the `Install` row, then the remaining table commands on the unmodified
checkout. Red baseline → STOP and report.

**Verify**: every command matches its expected result.

### Step 1: Move the modules verbatim

1. `git mv apps/refinery/analytics_read_model.py news_collector/serving/analytics_read_model.py`
2. `git mv apps/refinery/bulk_helper.py news_collector/serving/bulk_helper.py`
3. `git mv apps/refinery/published_content.py news_collector/logic/workflows/published_content.py`
4. Fix only the imports that reference the old module paths *inside* the moved
   files (e.g. `apps.refinery.bulk_helper` docstring references), and inside
   `news_collector/logic/workflows/published_content.py` keep its relative
   imports working (it imported from `news_collector.*` already — verify with
   `grep -n "^from\|^import" <file>`).
5. Do **not** rename public functions.

**Verify**: `python -c "import news_collector.serving.analytics_read_model, news_collector.serving.bulk_helper, news_collector.logic.workflows.published_content"` → exit 0.

### Step 2: Rewire callers

6. `news_collector/serving/api.py` — update the four import sites to the new
   paths. Keep them function-local if that is the file's local convention for
   heavy imports (check the neighbouring endpoints).
7. `apps/refinery/main.py:16` and `apps/refinery/admin_panel.py:60-62,951` —
   point them at the new locations. Prefer direct imports over shims.
8. **Shim rule:** if any other consumer outside these files imports the old
   paths (grep again after step 7: `grep -rn "apps.refinery.analytics_read_model\|apps.refinery.bulk_helper\|apps.refinery.published_content" --include=*.py .`),
   leave a one-line re-export shim (`from news_collector... import *  # noqa`) at
   the old path and say so in the ledger row. Otherwise delete the old files
   (which `git mv` already did).

**Verify**: `grep -rn "apps.refinery" --include=*.py news_collector/` → **no matches**;
`grep -rn "apps.refinery.\(analytics_read_model\|bulk_helper\|published_content\)" --include=*.py apps/ tests/ scripts/ tools/` → no matches (or only documented shims).

### Step 3: Pin the invariant with a test

9. Add `tests/unit/serving/test_serving_import_surface.py`:
   - assert that importing `news_collector.serving.api` (or calling `create_app`)
     does not require `apps.*` — e.g. by asserting no module under
     `news_collector/` contains `apps.refinery` (AST or text scan) and that the
     four endpoint modules resolve without importing `apps`;
   - assert the three moved modules import cleanly with `apps` absent from
     `sys.modules` (delete the entry in a monkeypatched state).
   Model the file after `tests/unit/serving/test_serving_image_security.py`.

**Verify**: `.venv/bin/pytest tests/unit/serving -q --no-cov` → all pass.

### Step 4: Prove the production shape

10. If Docker is available: build the image, run it with `ADMIN_API_KEY=test`,
    and curl `/v1/admin/analytics` → expect **200** (with a JSON body) instead of
    500. Record the status code.
11. If Docker is unavailable: run the in-process proof instead — start the app
    with the repo's `apps/` directory temporarily hidden from `sys.path`
    (e.g. `docker`-less alternative: run `python -c` in a temp worktree copy that
    omits `apps/`, using `git worktree add` + removing `apps/`), then hit the
    same route with `TestClient`. Record what you actually ran.

**Verify**: the recorded status code / test result, plus the ledger note.

## Test plan

- New: `tests/unit/serving/test_serving_import_surface.py` (Step 3) — the
  regression test for this bug: it must fail if any `news_collector/` module
  imports `apps.*`.
- Keep all existing serving tests green (`tests/test_serving_admin_api.py`
  exercises the analytics/content routes over `TestClient`).

**Verify**: `make test && make test-boundaries && make test-contracts` → green.

## Done criteria

All must hold:

- [ ] `make lint`, `make type`, `make test`, `make test-boundaries`, `make test-contracts` exit 0
- [ ] `grep -rn "apps.refinery" --include=*.py news_collector/` → no matches
- [ ] New import-surface test exists and fails on the pre-change code (prove once)
- [ ] Container (or documented equivalent) proof recorded: `/v1/admin/analytics` → 200
- [ ] `make inventory-check` exits 0 (moved/added files); if it reports drift, run
      `make inventory-refresh` and include the regenerated `audit/00_inventory.json`
- [ ] `git diff --name-only main...HEAD` lists only in-scope files
- [ ] `plans/README.md` row 134 updated; `make plans-ledger-check` → OK

## STOP conditions

- The excerpts do not match the live code (drift), or a moved module turns out to
  import Streamlit / UI state (would change the plan's premise).
- An importer outside the enumerated set appears and cannot be updated in scope.
- The container cannot be built for environmental reasons *and* the in-process
  proof is also impossible → report without claiming the proof.

## Maintenance notes

- The import-surface test is the guard: any future `from apps.…` in
  `news_collector/` must fail CI.
- Reviewer should scrutinise: that `published_content.py`'s move did not change
  its git/requests behaviour, and that the legacy Streamlit panel still starts
  (`make refinery` is not run by CI — say so in the PR).
- **Deferred:** deleting the legacy Streamlit panel entirely. Unblocked by the
  operator confirming `apps/admin/` is flawless in daily use (AGENTS.md
  "Safe entry points").
