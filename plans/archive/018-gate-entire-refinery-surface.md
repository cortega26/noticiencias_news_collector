# Plan 018: Gate the entire Refinery surface before rendering secrets or mutations

> **Executor instructions**: Follow this plan step by step and run every verification command. Stop on any condition below; do not improvise. When complete, update plan 018 in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat e43bd30..HEAD -- apps/refinery/admin_panel.py docker-compose.yml tests/decompose_refinery/test_refinery_auth.py`
> If these files changed, compare the excerpts below with live code before continuing.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: security
- **Planned at**: backend `e43bd30`, 2026-07-21

## Why this matters

Refinery currently authenticates only its Operations and Content Management tabs. Before either gate runs, Streamlit renders controls preloaded with the GitHub token and UI token; other unauthenticated tabs can save secrets, enable the unsafe bypass, and mutate source configuration. Docker publishes port 8501 on every host interface. Authentication must be a page-level boundary, not an action-local convention.

## Current state

- `apps/refinery/admin_panel.py:360-395` defines `require_refinery_auth`; it uses constant-time comparison and logs failed attempts without secrets. Preserve those properties.
- `apps/refinery/admin_panel.py:398-404` loads secrets and runtime configuration before any page-level gate.
- `apps/refinery/admin_panel.py:1453-1476` passes existing secret values into password widgets and saves them from an unguarded tab.
- `apps/refinery/admin_panel.py:2009` and `:2518` are the only current auth calls.
- `apps/refinery/admin_panel.py:2941-2980` writes and deletes source configuration without checking auth.
- `docker-compose.yml:16-20` runs Streamlit at `0.0.0.0` and maps `8501:8501`.
- Tests use AST extraction to avoid importing the top-level Streamlit script; follow `tests/decompose_refinery/test_refinery_auth.py:27-66`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Focused tests | `.venv/bin/python -m pytest tests/decompose_refinery/test_refinery_auth.py -q` | all pass |
| Refinery regression | `.venv/bin/python -m pytest tests/decompose_refinery tests/unit/refinery -q` | all pass |
| Lint | `.venv/bin/python -m ruff check apps/refinery/admin_panel.py tests/decompose_refinery/test_refinery_auth.py` | exit 0 |
| Format | `.venv/bin/python -m black --check apps/refinery/admin_panel.py tests/decompose_refinery/test_refinery_auth.py` | exit 0 |

## Scope

**In scope**: `apps/refinery/admin_panel.py`, `docker-compose.yml`, `tests/decompose_refinery/test_refinery_auth.py`, and a short operator note under `docs/` if needed.

**Out of scope**: replacing token auth with OAuth, building a reverse proxy, changing publication behavior, rotating secret values, or splitting the whole 2,900-line admin panel.

## Git workflow

- Branch: `advisor/018-gate-refinery-surface`
- Use conventional commits, e.g. `fix(security): gate entire refinery surface`.
- Do not push or open a PR unless instructed.

## Steps

### Step 1: Move authentication to the page boundary

After minimal page setup, load only the UI token/bypass configuration required for authentication, call `require_refinery_auth`, and call `st.stop()` when it returns false. This must occur before tabs are constructed, secrets are placed in widgets, database managers are created, or mutable configuration is loaded. Remove redundant tab-local calls after the global gate is proven.

**Verify**: focused auth tests pass and an AST/source-order test proves the global gate precedes the first `st.tabs` call.

### Step 2: Stop round-tripping existing secrets through the browser

Render secret inputs blank. Treat blank input as “retain current value”; use an explicit checkbox/button to clear a secret. Never pass an existing token as a widget `value`, success message, log field, or exception detail. The unsafe bypass may remain only if the page is already authenticated and its warning remains prominent.

**Verify**: add tests asserting the source does not pass `secrets.get("GITHUB_TOKEN"...)` or the stored UI token to `st.text_input`, and that save semantics preserve on blank / replace on nonblank / clear only explicitly.

### Step 3: Narrow the default Docker exposure

Keep Streamlit listening inside the container as required, but bind the published host port to loopback (`127.0.0.1:8501:8501`). Document that remote access requires an authenticated TLS reverse proxy or an explicit operator override.

**Verify**: `docker compose config` exits 0 and the rendered port binding uses host IP `127.0.0.1`.

## Test plan

- Extend the existing AST-based auth tests for missing, wrong, correct, and bypass credentials.
- Add ordering coverage: unauthenticated execution cannot reach tab construction.
- Add secret-widget regression assertions without embedding any real credential.
- Manually launch with a test token and verify unauthenticated sessions see only the auth prompt; authenticated sessions can reach every tab.

## Done criteria

- [ ] No tab or mutating callback renders before the global auth gate.
- [ ] Existing secret values are never sent to password widgets.
- [ ] Docker binds Refinery to loopback by default.
- [ ] Focused and Refinery regression tests pass.
- [ ] Ruff and Black checks pass.
- [ ] Only in-scope files and `plans/README.md` changed.

## STOP conditions

- Stop if Streamlit cannot authenticate before tab construction without importing secret-backed application state.
- Stop if remote production access currently depends directly on `8501:8501`; report the deployment topology before changing the binding.
- Stop if a secret value appears in test output, logs, fixtures, or a diff.

## Maintenance notes

Every new Refinery tab inherits the page gate; reviewers should reject action-local auth as the sole boundary. If stronger identity or multiple users become necessary, replace this page gate deliberately rather than layering another partial gate over it.
