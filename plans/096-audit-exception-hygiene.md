# Plan 096: Unify the security-audit exception policy (document CVE-2026-0994, retire expired protobuf ignore)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat e77a039..HEAD -- Makefile SECURITY.md scripts/security_gate.py requirements-security.lock requirements-refinery.lock docs/security_removal_plan.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `e77a039`, 2026-09-16

## Why this matters

Two audit suppressions bypass the repo's own time-limited-exception policy
(`scripts/security_gate.py` requires `reason` + `expires_on` with expiry
enforcement): `make quality` silently ignores `CVE-2026-0994` via an
undocumented CLI flag that the other two audit paths (`quality-ci`,
`security`) don't share — so one gate passes what the others fail; and
`make security-dev` still ignores the protobuf advisory on an authorization
that expired **2026-03-01**, which `SECURITY.md` itself calls unresolved drift.
After this plan, all three audit paths agree and every suppression is scoped,
justified, and expiring.

## Current state

The relevant files, each with one line on its role:

- `Makefile` — the three divergent audit invocations (lines 177, 196, 292-293, 305-310)
- `scripts/security_gate.py` — the enforced allowlist model (lines 31-75)
- `SECURITY.md` — policy record, including the self-reported drift (lines 19-29)
- `docs/security_removal_plan.md` — removal checklist for the expired exception

Excerpts of the code as it exists today:

`Makefile:177` (undocumented, path-specific):

```make
@$(PIP_AUDIT) -r requirements.lock --desc --ignore-vuln CVE-2026-0994
```

`Makefile:196` and `:292-293` — the same audit WITHOUT the flag (paths disagree).

`Makefile:308-309`:

```make
@$(PIP_AUDIT) -r requirements-security.lock --desc --ignore-vuln GHSA-7gcm-g887-7qv7
@$(PIP_AUDIT) -r requirements-refinery.lock --desc --ignore-vuln GHSA-7gcm-g887-7qv7
```

`scripts/security_gate.py:31-44` — the model to converge on (expiring entries; expired entries hard-fail at lines 65-73; NLTK entry expires 2026-09-30):

```python
# pip-audit advisories that remain accepted risks until upstream fixes ship.
# Each entry must include an expiry date so suppressions cannot become permanent.
PIP_AUDIT_ALLOWLIST: dict[str, dict[str, str]] = {
    ...
    "GHSA-8mgp-746c-j5xp": {
        "reason": "NLTK 3.10.3 path-sandbox bypass with no upstream fix yet; ...",
        "expires_on": "2026-09-30",
    },
}
```

`SECURITY.md:24-28`:

```
`make security-dev` still passes `--ignore-vuln GHSA-7gcm-g887-7qv7` for
protobuf. Its previously documented authorization expired **2026-03-01**,
and that Make recipe does not enforce expiry. This is unresolved policy/code
drift, not a renewed exception. ...
```

Repo conventions that apply here:

- Change Matrix: dependency/security change = Critical → baseline + `make quality` where applicable.
- Docs follow code (§9): `SECURITY.md` + `docs/security_removal_plan.md` update in the same change; `make docs-check` must stay green.

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Install   | `make bootstrap`         | declared   | exit 0 |
| Lint      | `make lint`              | declared   | exit 0 |
| Audit     | `make security`          | declared   | exit 0 |
| Quality   | `make quality`           | declared   | exit 0 |
| Docs gate | `make docs-check`        | declared   | exit 0 |

## Scope

**In scope** (the only files you should modify):

- `Makefile` (the three audit invocations + `security-dev` target)
- `scripts/security_gate.py` (allowlist entries, only if the investigation justifies one)
- `SECURITY.md`, `docs/security_removal_plan.md` (policy record updates)
- Lockfiles (`requirements.lock`, `requirements-security.lock`, `requirements-refinery.lock`) — ONLY via the repo's sync flow (`scripts/sync_lockfiles.py` / documented lock process), never hand-edited

**Out of scope** (do NOT touch, even though they look related):

- Upgrading the affected packages themselves beyond what the lock sync produces — if an upgrade is needed, do the lock-sync + test run, not a manual pin bump.
- The NLTK `GHSA-8mgp` entry (expires 2026-09-30) — re-check it while you're here and note the result, but renewing it is a separate decision; do not silently extend it.
- Any production code.

## Git workflow

- Branch: `advisor/096-audit-exception-hygiene`
- Conventional commits, e.g. `chore(security): unify pip-audit exception policy`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `Install`, then `make security` on the unmodified checkout and RECORD the
per-scanner verdicts (pip-audit/bandit/gitleaks) verbatim. Then `Lint`.

- If `make security` already fails on the clean tree, record the exact failure — that is your starting evidence, not a STOP (you're here to change these gates deliberately). Any *other* `declared` command failing is a STOP — report it.

**Verify**: baseline verdicts recorded; `make lint` exits 0.

### Step 1: Investigate CVE-2026-0994 (no change yet)

1. Run the un-ignored audit read-only: `.venv/bin/python -m pip_audit -r requirements.lock --desc` (or the repo's pinned invocation) and capture the `CVE-2026-0994` entry: affected package + versions, severity, and whether the package is reachable runtime code or build-only.
2. Check git history for the flag's origin: `git log -S CVE-2026-0994 --oneline -- Makefile` — who added it, when, with what message.
3. Verdict, one of:
   - (a) Fixed upstream / not actually present → delete the flag everywhere.
   - (b) Real but accepted risk → move it into the `PIP_AUDIT_ALLOWLIST` model in `security_gate.py` with `reason` + short `expires_on`, wire the gate so ALL THREE audit paths enforce the same set, and delete the Makefile `--ignore-vuln` flag.
   - (c) Real and unacceptable → remove the flag and file/upgrade work as a follow-up (STOP and report — do not start the upgrade inside this plan).

**Verify**: written verdict (a/b/c) with the advisory text quoted in your report (advisory metadata only — no exploit detail needed).

### Step 2: Resolve the expired protobuf ignore

1. Re-run the lock sync for the security/refinery locks per the repo flow and re-audit: does `GHSA-7gcm-g887-7qv7` still fire?
2. If fixed → delete both `--ignore-vuln GHSA-7gcm-g887-7qv7` flags from `security-dev`, check off `docs/security_removal_plan.md`, update `SECURITY.md` (exception retired, date).
3. If still firing → do NOT extend the inline flag. Either upgrade protobuf through the sync flow, or replace the inline flag with an enforced, expiring entry per the allowlist model + a dated `SECURITY.md` note + removal-plan update. If neither is achievable quickly, STOP and report (an expired suppression must not be quietly renewed).

**Verify**: `grep -n "ignore-vuln" Makefile` → no undocumented inline flags remain (every remaining one, if any, points at the enforced model).

### Step 3: Converge the three audit paths + docs

1. After Steps 1-2, `make quality`, `make quality-ci` (or at least its pip-audit leg — read the target first; don't run the whole CI-only target if it requires CI env), and `make security` must implement the SAME exception set. Document the single source of truth (the allowlist in `security_gate.py`) in a comment at each Makefile invocation.
2. Update `SECURITY.md` + `docs/security_removal_plan.md` to describe the end state; `make docs-check` green.

**Verify**: `make security` → exit 0; `make quality` → exit 0; `make docs-check` → exit 0; all three audit paths reference one exception source.

## Test plan

- No new unit tests expected (Make/policy change). If you add an allowlist entry, add/extend the gate's own tests if any exist (check `tests/` for `security_gate` coverage first).
- Verification is the gates themselves: `make security`, `make quality`, `make docs-check`, plus `make lint`.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `make lint`, `make security`, `make quality`, `make docs-check` all exit 0
- [ ] `grep -n "ignore-vuln" Makefile` shows no bare undocumented flag (each remaining occurrence, if any, cites the enforced allowlist + expiry)
- [ ] `SECURITY.md` no longer describes the protobuf item as unresolved drift (retired or renewed-with-expiry)
- [ ] `git diff --name-only e77a039...HEAD` lists only the in-scope files (lockfile diffs from the official sync flow are acceptable — call them out)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- Step 1 verdict is (c) — real, unacceptable vuln needing an upgrade (report; don't start it here).
- The protobuf advisory still fires AND no upgrade path exists within the sync flow (report; don't renew silently).
- The NLTK `GHSA-8mgp` entry already expired relative to today (2026-09-30) and the gate hard-fails for that reason — note it prominently; renewing it is out of scope.
- A `declared` command (other than the deliberately-changed audit verdicts) fails on the unmodified checkout.

## Maintenance notes

- Every future suppression must enter through `PIP_AUDIT_ALLOWLIST` with reason + expiry — never a Makefile flag. Say this in `SECURITY.md` so the next exception follows the model.
- Watch the NLTK 2026-09-30 expiry: the gate fails closed on expiry by design; calendar it.
- Reviewers: confirm lockfile diffs came from the sync flow (hashes consistent), not hand edits.
- **Deferred:** nothing — this plan closes both items or reports why it can't.
