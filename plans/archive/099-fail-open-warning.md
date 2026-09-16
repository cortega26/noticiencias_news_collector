# Plan 099: Log loudly on dev-only auth fail-open (unset API keys)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat e77a039..HEAD -- news_collector/serving/api.py tests/test_webhook.py tests/test_serving_admin_api.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `e77a039`, 2026-09-16

## Why this matters

The webhook/admin verifiers already fail closed outside `development` (plan
021) — this plan does NOT relitigate that settled tradeoff. The residual gap:
when the key is unset AND the environment is `development`, both functions
`return` silently, and the shipped default environment IS `development`
(`config.toml`, schema default, `RuntimeSettings` default). A production deploy
that forgets the key and never sets the environment tier serves the full admin
mutator surface with zero log signal. A loud warning on every fail-open makes
that misconfiguration visible in every log tail. After this plan, silent
fail-open no longer exists.

## Current state

The relevant files, each with one line on its role:

- `news_collector/serving/api.py` — `verify_webhook_token` (lines 585-599), `verify_admin_token` (lines 629-643)

Excerpts of the code as it exists today:

`serving/api.py:585-599` (webhook; admin mirrors at 629-643):

```python
webhook_api_key = os.environ.get("WEBHOOK_API_KEY", "")
if not webhook_api_key:
    runtime = get_runtime_config()
    if runtime.environment != "development":
        logger.error(...)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook authentication is not configured for this environment",
        )
    return  # explicit development-only fail-open
```

Defaults making `development` the out-of-box tier (verified, not changing them
here): `news_collector/config/runtime.py:25` (`environment: str = "development"`),
`config.toml:2` (`environment = "development"`), `noticiencias/config_schema.py`
schema default.

Repo conventions that apply here:

- The fail-closed-outside-dev behavior is a documented plan-021 decision — preserve it exactly; this plan only adds signal to the documented dev path.
- Log via the module `logger` (loguru-style, as the surrounding code does).
- Tests: webhook tests in `tests/test_webhook.py`, admin tests in `tests/test_serving_admin_api.py`.

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Install   | `make bootstrap`         | declared   | exit 0 |
| Lint      | `make lint`              | declared   | exit 0 |
| Type      | `make type`              | declared   | exit 0, ratchet passes |
| Tests     | `make test`              | declared   | all pass |

## Scope

**In scope** (the only files you should modify):

- `news_collector/serving/api.py` (the two fail-open `return` sites only)
- `tests/test_webhook.py`, `tests/test_serving_admin_api.py` (new cases only)

**Out of scope** (do NOT touch, even though they look related):

- The environment default (`development`) and `config.toml` — changing the shipped default is a deployment-behavior decision for the operator, not this plan. (Recommend it in your final report as a one-line operator action, don't implement it.)
- The 503 fail-closed branch — settled, covered.
- Startup-time key checks — tempting, but the per-request warning is the minimal complete fix; don't build a startup gate here.

## Git workflow

- Branch: `advisor/099-fail-open-warning`
- Conventional commits, e.g. `fix(security): warn loudly on dev-only auth fail-open`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `Install`, then `Lint`, `Type`, `Tests` on the unmodified checkout. On any
`declared`-command failure on the clean tree: **STOP and report** with exact output.

**Verify**: all commands match their expected results on the unmodified checkout.

### Step 1: Add the warning at both fail-open sites

At each `return  # explicit development-only fail-open` (webhook ~line 599,
admin ~line 643), insert before the return:

```python
logger.warning(
    "WEBHOOK_API_KEY is not set and environment is 'development' — "
    "serving webhook/admin requests WITHOUT authentication. "
    "Set the key and a non-development environment tier in production."
)
```

(and the `ADMIN_API_KEY` analogue). Warning level (not error): the process is
behaving as configured for local dev; but it must be unmissable. Rate-limit
consideration: this fires per unauthenticated request — acceptable (it indicates
an active misconfiguration worth noise); do NOT build dedup logic.

**Verify**: `make lint` → exit 0.

### Step 2: Add tests

1. With key unset + environment `development` (mirror how existing tests set
   env/refresh runtime config — read the current 503-test setup first and copy
   its env-handling pattern): request succeeds AND a warning record with
   "WITHOUT authentication" is captured (caplog/loguru sink pattern used in this repo — check neighboring log-assertion tests first).
2. With key unset + environment `staging` (or any non-development): 503, no warning (pins the fail-closed branch untouched).

**Verify**: `.venv/bin/python -m pytest tests/test_webhook.py tests/test_serving_admin_api.py -q` → all pass including new tests.

### Step 3: Run the full gates

**Verify**: `make lint && make type && make test` → all exit 0.

## Test plan

- New: fail-open emits the warning + succeeds (dev); fail-closed 503s without it (non-dev).
- Existing webhook/admin suites green (warning must not break log-snapshot assertions — check for any).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `make lint`, `make type`, `make test` all exit 0
- [ ] Both fail-open sites log the warning (grep for the marker string in `api.py`: 2 sites)
- [ ] New warning tests exist and pass
- [ ] `git diff --name-only e77a039...HEAD` lists only the in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- Existing tests already assert silence (no warning) on the fail-open path in a way that suggests the silence is intentional — report it as a behavior dispute.
- The repo's log-assertion pattern can't capture the warning cleanly (report the harness gap instead of shipping an untested log line).
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

- Operator action (report, don't implement): consider shipping `config.toml` with a non-development default or requiring explicit `environment = "development"` opt-in for local runs — that removes the footgun this warning only illuminates.
- If key-rotation/missing-key alerting is ever built, these two log lines are the signal to key on.
- Reviewers: confirm the warning text names the exact env var and the exact consequence.
- **Deferred:** startup-time configuration gate refusing to serve without keys outside dev — bigger behavior change, needs an operator decision.
