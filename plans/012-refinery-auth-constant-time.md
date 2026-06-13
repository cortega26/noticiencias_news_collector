# Plan 012: Harden Refinery auth — constant-time token compare + failed-attempt logging

> **Executor instructions**: Follow step by step; verify each step. Honor STOP
> conditions. Update this plan's row in `plans/README.md` when done.
>
> **Drift check (run first)**: `git diff --stat b30248f..HEAD -- apps/refinery/admin_panel.py`
> If the file changed, re-confirm the excerpt before editing; on a mismatch, STOP.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security (hardening)
- **Planned at**: commit `b30248f`, 2026-06-12
- **Confidence note**: this is hardening, not a live exploit. The Refinery already
  has a working token gate; this tightens two small weaknesses.

## Why this matters

The Refinery admin panel gates write/publish actions behind a UI token. The gate is functional, but the comparison `entered == token` is **not constant-time**, and failed attempts are **not logged**. Constant-time comparison (`hmac.compare_digest`) is the standard, near-free fix for secret comparison, and logging failed auth gives an audit trail for a tool that can publish content and reset the database. Low severity, low effort, clearly correct — worth doing while the area is fresh.

(Out of scope and intentionally unchanged: the `REFINERY_UI_UNSAFE_ALLOW=1` bypass is a deliberate, warned escape hatch; the single-shared-token model is the chosen design.)

## Current state

```python
# apps/refinery/admin_panel.py:356-390
def require_refinery_auth(env_vars: dict[str, str], key: str = "auth_token") -> bool:
    bypass = (
        str(env_vars.get(REFINERY_UI_BYPASS_KEY, "")).strip() == "1"
        or os.getenv(REFINERY_UI_BYPASS_KEY) == "1"
    )
    if bypass:
        st.warning("⚠️ Autenticación desactivada vía REFINERY_UI_UNSAFE_ALLOW=1.")
        return True

    token = env_vars.get(REFINERY_UI_TOKEN_KEY) or os.getenv(REFINERY_UI_TOKEN_KEY)
    if not token:
        st.error("❌ Falta REFINERY_UI_TOKEN. ...")
        return False

    if st.session_state.get("refinery_ui_authenticated"):
        return True

    with st.expander("🔐 Acceso restringido", expanded=True):
        entered = st.text_input("Token de acceso", type="password", help="...", key=key)
        if entered:
            if entered == token:                      # <-- line 385: non-constant-time compare
                st.session_state["refinery_ui_authenticated"] = True
                st.success("Autenticación exitosa.")
                return True
            st.error("Token inválido.")               # <-- no logging of the failure
    return False
```

The file already imports `os` and uses a module logger elsewhere — confirm what logger is in scope (search the top of `admin_panel.py` for `logger`/`get_logger`/`logging`). The codebase's logger helper is `news_collector.utils.logger.get_logger` (used widely, e.g. `image_handler.py:24`).

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Find/refinery tests | `find tests -path '*refinery*' -name '*.py'; grep -rln "require_refinery_auth" tests/` | locate tests |
| Run refinery tests | `.venv/bin/pytest tests/decompose_refinery -q` (and any auth test found) | all pass |
| Lint | `make lint` | exit 0 |
| Import check | `.venv/bin/python -c "import ast,sys; ast.parse(open('apps/refinery/admin_panel.py').read()); print('ok')"` | `ok` |

(Note: `apps/refinery/` is excluded from `make type`/mypy and runs under a separate `.venv`; rely on `make lint` + the AST parse + any existing refinery tests.)

## Scope

**In scope:**
- `apps/refinery/admin_panel.py` — the comparison and failure-logging in `require_refinery_auth` only
- a test for `require_refinery_auth` (add to the refinery test area; create one if none exists)

**Out of scope:**
- The bypass mechanism, the token-storage model, rate limiting (rate limiting in a Streamlit rerun model is non-trivial and not warranted here — do NOT add it).
- Any other auth/secrets code.

## Git workflow

- Branch: `advisor/012-refinery-auth-constant-time`
- One commit; `fix(security): …` style.
- Do NOT push or open a PR.

## Steps

### Step 1: Constant-time comparison

Add `import hmac` at the top of `admin_panel.py` (with the other stdlib imports). Replace the compare:

```python
if entered:
    if hmac.compare_digest(str(entered), str(token)):
        st.session_state["refinery_ui_authenticated"] = True
        st.success("Autenticación exitosa.")
        return True
    logger.warning("refinery.auth.failed")  # use the in-scope logger; no token/value in the message
    st.error("Token inválido.")
```

`hmac.compare_digest` requires both args be `str` (or both `bytes`); wrap with `str(...)` to be safe. **Never** log the entered value or the token — log only the event.

If no module-level `logger` exists in `admin_panel.py`, add one near the top:
```python
from news_collector.utils.logger import get_logger
logger = get_logger().create_module_logger("RefineryAdminPanel")
```
**Note:** `get_logger()` takes **no** arguments (it returns a factory); `get_logger(__name__)` raises `TypeError`. The established pattern is `get_logger().create_module_logger("<name>")` — verified against `image_handler.py:26`. (Corrected post-execution 2026-06-13.)

**Verify:** `grep -n "entered == token" apps/refinery/admin_panel.py` → no matches; `grep -n "compare_digest" apps/refinery/admin_panel.py` → 1 match.

### Step 2: Test `require_refinery_auth`

Streamlit functions are awkward to test, but `require_refinery_auth` is mostly pure logic over `env_vars` + `st.session_state`. Add a test that:
- with `REFINERY_UI_BYPASS_KEY` env set to `"1"` → returns `True` (bypass path),
- with a token configured and `st.session_state["refinery_ui_authenticated"] = True` pre-set → returns `True` without prompting.

You will need to stub `st` (the test can monkeypatch the module's `st` with a minimal fake exposing `session_state` (a dict), `warning`, `error`, `success`, `text_input`, `expander`). Look at `tests/decompose_refinery/` for how the suite already imports/stubs the refinery module, and follow that pattern. If stubbing Streamlit proves heavier than the value here, at minimum add a focused unit test of the comparison logic by extracting nothing — instead test that `hmac.compare_digest` is used by asserting `require_refinery_auth` returns `False` for a wrong token and `True` for the correct one via the session-state shortcut. **If full Streamlit stubbing is impractical, STOP and report** — ship Step 1 (the real fix) with the AST/lint verification rather than forcing a brittle UI test.

**Verify:** `.venv/bin/pytest tests/decompose_refinery -q` (plus any new test) → all pass.

## Test plan

- New/extended test for `require_refinery_auth`: bypass path, already-authenticated path, and (if feasible) correct-vs-wrong token. Pattern: `tests/decompose_refinery/`.
- Verification: refinery tests green; `make lint` clean.

## Done criteria

ALL must hold:

- [ ] `entered == token` replaced with `hmac.compare_digest(...)`; `import hmac` added
- [ ] A failed auth attempt is logged (event only, no secret value)
- [ ] `grep -n "entered == token" apps/refinery/admin_panel.py` → no matches
- [ ] `apps/refinery/admin_panel.py` parses (AST check) and `make lint` exits 0
- [ ] A test covers at least the bypass + already-authenticated paths (or Step 2 STOP reported)
- [ ] Only `admin_panel.py` and a test file modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- Stubbing Streamlit for the test is disproportionately complex — ship Step 1 with AST/lint verification and report the test as deferred.
- `admin_panel.py` has no usable logger and adding `get_logger` pulls in heavy imports that break the refinery's separate-venv import (test with the AST/import check).
- The auth function has been restructured (drift).

## Maintenance notes

- A reviewer should confirm no token/entered value is ever logged and that the bypass + single-token design were left intact.
- Deferred (not in scope): if the Refinery is ever exposed beyond a trusted network, revisit with proper per-user auth and rate limiting — note for the owner.
