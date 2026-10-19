# Plan 143: Restore the dev-lock security gate and put it in CI

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 43aa3da9..HEAD -- requirements-security.lock requirements.lock requirements-refinery.lock scripts/sync_lockfiles.py Makefile .github/workflows/quality.yml SECURITY.md docs/security.md scripts/security_gate.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none, but **sequence against plans 138, 139, 142, 144, 145** for
  the shared CI files (and see the interaction with plan 144, which touches the
  same lock/venv area — run 144 after this one)
- **Category**: security / dependencies
- **Planned at**: commit `43aa3da9`, 2026-10-19 (re-opened with the decision below)

### Blocker note (2026-10-19) — the fix is unavailable upstream

The first execution attempt proved the bump cannot be delivered as specified:
`semgrep` — a direct dependency of the `security` extra — pins `mcp` **exactly**
(`mcp==1.29.0` in semgrep 1.180.0; every release from 1.173.0 through 1.181.0
pins the same version, verified against PyPI), so
`scripts/sync_lockfiles.py --upgrade-package mcp==1.30.0` fails with
`ResolutionImpossible`, and the advisory's fix versions (`1.30.0`, `2.2.0`) are
unreachable through this path. `make security-dev` fails closed on the advisory
by design (no severity in the record → `UNKNOWN` → HIGH), which is the documented
policy — the gate is not wrong, the fix is missing.

**Operator decision required (the plan cannot choose):**

- **(a) Wait upstream.** No semgrep release lifts the pin as of 1.181.0. Keep
  `security-dev` unwired until a bump lands, and revisit then. Cost: the dev-lock
  advisory stays unknown-to-CI, and the ledger's stale "security-dev fully green
  (2026-10-12)" claim must stay corrected.
- **(b) Decouple semgrep from the audited environment.** Move semgrep (and its
  `mcp` pin) out of the `security` extra / the audited lock — e.g. install it
  unpinned in the CI job that runs it. Cost: toolchain restructuring; the
  advisory would need a recorded disposition (it is semgrep's own MCP transport,
  not production-reachable).
- **(c) A dated `PIP_AUDIT_ALLOWLIST` entry** for `GHSA-84m7-p3x7-pcfv` with a
  reason and an expiry — the mechanism `SECURITY.md` provides. Cost: it hides a
  real advisory in a dev-only tool; the plan forbade the executor from doing it
  unilaterally, which is exactly why this needs the operator's word.

Do not re-execute until one option is chosen. (Independent note from the same
run: locally, `make security` can be red because `gitleaks 8.18.1 detect` scans
every ref in the shared object store, including sibling unmerged branches; a
HEAD-scoped scan is clean and CI is unaffected because it checks out one ref.)

### Decision (2026-10-19) — option (c), bounded and dated

The reviewer adopts **option (c)** — one dated `PIP_AUDIT_ALLOWLIST` entry — and
re-opens the plan with these constraints:

- **Why this option:** the advisory is in `mcp`, semgrep's MCP server. It appears
  only in `requirements-security.lock` (never in `requirements.lock` or the
  refinery lock), ships in no image, and is not reachable from production code or
  untrusted input. Its only fix path is blocked upstream (semgrep pins
  `mcp==1.29.0` exactly across 1.173.0–1.181.0).
- **Why not wait:** a permanently red gate teaches everyone to ignore the gate,
  blocks plans 144/145, and makes every "security is green" claim unverifiable —
  a worse failure mode than a visible, bounded exception.
- **Why not decouple semgrep now:** the separate-environment fix is the durable
  answer, but it is a toolchain restructuring that belongs with plan 144 (which
  already introduces the parity check and scopes the split). Mixing it in here
  would turn a small fix into a toolchain change.
- **Bounded:** one entry for `GHSA-84m7-p3x7-pcfv`, a `reason` naming the semgrep
  pin and the dev-only scope, and an `expires_on` of **2026-11-30**. The gate
  must still fail on every other finding, and on this one after the expiry.
- **Observed:** Step 4 (wire `security-dev` into `quality.yml`) is required, so
  the exception is exercised by CI instead of a manual command nobody runs.

## Why this matters

`make security-dev` is red today. `pip-audit -r requirements-security.lock`
reports `mcp 1.29.0` → `GHSA-84m7-p3x7-pcfv` (fix 1.30.0/2.2.0), the allowlist in
`scripts/security_gate.py:33-40` is intentionally empty, and the gate treats a
missing severity as fail-closed. The ledger's "security-dev fully green
(2026-10-12)" is stale, so the next executor who follows it hits an unexplained
exit 1 — and the natural reaction (add an allowlist entry) would re-introduce the
expiry debt that plan 096 just retired. On top of that, `security-dev` is in **no**
CI path (`make verify-ci` and every workflow omit it), so a dev/refinery-lock
advisory is invisible until someone runs it by hand. Exposure is limited
(`mcp` is semgrep's own dependency in the dev/security environment and is absent
from the runtime and refinery locks — verified), so this is a hygiene and
truthfulness fix, not an incident.

## Current state

- `requirements-security.lock:1195-1198`:

```
mcp==1.29.0 \
    --hash=sha256:52d0… \
    --hash=sha256:f5a0… \
    # via semgrep
```

- `scripts/security_gate.py:33-40` — `PIP_AUDIT_ALLOWLIST: dict[str, dict[str, str]] = {}`
  with the comment "2026-10-12: empty … Verified: `pip-audit -r
  requirements-security.lock` -> no known vulnerabilities."
- `scripts/security_gate.py` — severity mapping (`UNKNOWN` → rank 3 = HIGH),
  `pip_audit_findings()` skips allowlisted ids/aliases, main exits 1 when
  findings survive the threshold.
- `Makefile:343-346` — `security-dev` audits `requirements-security.lock` and
  `requirements-refinery.lock`, writing `reports/security/status-dev.json`.
- `Makefile:249` — `verify-ci` does **not** include `security-dev`.
- `SECURITY.md:18,25-33` and `docs/security.md:18` — the policy text to keep in
  sync.
- `scripts/sync_lockfiles.py` — the sanctioned regeneration path
  (`python scripts/sync_lockfiles.py --help` for the exact flags before using it).

## Commands you will need

| Purpose                | Command                                                                 | Provenance | Expected on success                    |
|------------------------|-------------------------------------------------------------------------|------------|----------------------------------------|
| Install/baseline       | `make bootstrap`                                                        | declared   | exit 0                                 |
| Current failure proof  | `.venv/bin/pip-audit -r requirements-security.lock --format json \| head -c 400` | executed (advisor ran it: 1 finding) | shows the mcp finding |
| Dev/security gate      | `make security-dev`                                                     | declared   | exits 1 today, 0 after the change      |
| Runtime gate           | `make security`                                                         | declared   | exit 0                                 |
| Quality gate           | `make quality-ci`                                                       | declared   | exit 0                                 |
| Ledger                 | `make plans-ledger-check`                                               | declared   | `validate_plans_ledger: OK`            |

Provenance: the `executed` row is the advisor's read-only `pip-audit` run against
the committed lock (no files written). Everything else is `declared`.

## Scope

**In scope**:

- `requirements-security.lock` — regenerate via `scripts/sync_lockfiles.py`
- `requirements.lock`, `requirements-refinery.lock` — only if the tool regenerates
  them as part of the same run (accept removals-only diffs; if unrelated churn
  appears, STOP)
- `scripts/security_gate.py` — **exactly one** dated `PIP_AUDIT_ALLOWLIST` entry
  (see the decision note); do not add a second entry or change the gate's logic
- `SECURITY.md`, `docs/security.md` — record the exception, its reason and expiry
- `.github/workflows/quality.yml` — add the `security-dev` leg
- `Makefile` — only if a `security-dev` change is needed to run in CI

**Out of scope** (do NOT touch):

- `scripts/security_gate.py`'s allowlist (leave it empty) and its severity logic.
- `Makefile:78-81`'s bootstrap install order (plan 144 owns the venv/lock
  relationship) — do not try to fix the override problem here.
- Any other lockfile content beyond what the tool regenerates.

## Git workflow

- Branch: `advisor/143-dev-lock-security-gate`
- Conventional commit, e.g. `fix(security): bump mcp in the dev lock and gate it in CI (plan 143)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `make bootstrap`, `make lint`, `make type`, `make security`, then
`make security-dev` and record the failure verbatim.

**Verify**: the first four exit 0; `security-dev` fails with the mcp finding (if
it fails for a *different* reason, STOP — the environment differs from the audit).

### Step 1: Re-verify the finding yourself

1. Run `.venv/bin/pip-audit -r requirements-security.lock --format json` and
   confirm the only findings are the mcp advisory (and that
   `pip-audit -r requirements.lock` and `-r requirements-refinery.lock` are
   clean). Record the ids.
2. Read the advisory's metadata (severity, affected versions, fix versions) from
   the pip-audit output. Do not paste advisory bodies into the repo.

**Verify**: the recorded finding list matches the expectation above.

### Step 2: Record the dated exception (the bump is unavailable upstream)

3. Do **not** attempt the lock upgrade — the blocker note records that it cannot
   succeed (`ResolutionImpossible`; semgrep pins `mcp==1.29.0`). Leave
   `requirements-security.lock` untouched.
4. In `scripts/security_gate.py`, add **one** entry to `PIP_AUDIT_ALLOWLIST`:
   - the advisory id the gate matches on (`GHSA-84m7-p3x7-pcfv`, and the alias
     form if the dict documents one — read `_active_pip_audit_allowlist` first);
   - `reason`: semgrep 1.180.0 pins `mcp==1.29.0` exactly (no release through
     1.181.0 lifts it); the package is dev-only, absent from the runtime and
     refinery locks and from every image; durable fix tracked by plan 144;
   - `expires_on`: `2026-11-30`.
   Follow the structure the dict already documents (reason + expiry are
   mandatory). Do not touch the severity mapping, the finder logic, or any other
   entry.
5. Confirm the runtime locks still do not contain `mcp`, and that the entry is
   the only change in the gate script (`git diff`).

**Verify**: `make security-dev` exits 0 and prints "All dev/refinery audits
passed"; temporarily set the entry's expiry to a past date and confirm the gate
fails again (prove the expiry is load-bearing), then restore `2026-11-30`;
`grep -n "^mcp==" requirements*.lock` → only the security lock, unchanged version.

### Step 3: Keep the record true

5. Update `SECURITY.md` (the dev-lock verdict section) and `docs/security.md:18`
   region: state the new pinned version, the date, and that the allowlist remains
   empty. Keep the existing structure; do not rewrite policy.
6. Update `plans/README.md`'s stale "security-dev fully green (2026-10-12)" claim
   — the row/paragraph that carries it — so the ledger stops asserting a state
   that the advisory broke.

**Verify**: `make docs-check` exits 0; `grep -rn "security-dev" SECURITY.md docs/security.md plans/README.md` shows consistent text.

### Step 4: Make the gate observable

7. Wire `make security-dev` into CI where the security toolchain already exists:
   add a step to `.github/workflows/quality.yml` after the existing quality
   steps (`run: make security-dev`). It is a pip-audit run over two lockfiles —
   no installs beyond what the job already has.
8. Alternatively, add it to `verify-ci`'s composition — but check the runtime
   cost first and state the choice in the ledger row. Prefer `quality.yml`
   (already the security home) unless you find a strong reason otherwise.
9. Update `docs/ci.md` if the workflow list changes.

**Verify**: `grep -n "security-dev" .github/workflows/quality.yml Makefile docs/ci.md` → the wiring is visible; YAML parses.

## Test plan

- No new unit tests: the deliverable is the lock bump + wiring. Verification is
  the two `make security*` targets plus the recorded `pip-audit` output.
- If `scripts/security_gate.py` has tests, run them
  (`.venv/bin/pytest tests/test_security_gate.py -q --no-cov`) and keep them green.

**Verify**: `make security && make security-dev && make quality-ci` → exit 0.

## Done criteria

All must hold:

- [ ] `make security-dev` exits 0; `make security` and `make quality-ci` still exit 0
- [ ] `pip-audit` over all three locks reports no findings (output recorded)
- [ ] The allowlist in `scripts/security_gate.py` is still empty (diff proves it)
- [ ] `security-dev` runs in CI; `docs/ci.md`/`SECURITY.md`/`docs/security.md` agree
- [ ] The stale ledger claim is corrected
- [ ] `git diff --name-only main...HEAD` lists only in-scope files
- [ ] `plans/README.md` row 143 updated; `make plans-ledger-check` → OK

## STOP conditions

- `security-dev` fails for anything other than the mcp advisory → report; the
  environment differs from the audit.
- The upgrade path would change the runtime locks beyond removals, or would
  upgrade semgrep itself (a bigger decision) → STOP and report the resolver output.
- `make quality-ci` goes red after the change → report with the diff; do not
  weaken the gate.

## Maintenance notes

- The empty allowlist is a deliberate stance: any future residual entry must
  carry a reason and an expiry date (the gate enforces this).
- Reviewer should scrutinise: that the lock diff is minimal and produced by the
  sanctioned script (not hand-edited), and that CI now runs the dev-lock audit.
- **Deferred:** auditing the sibling frontend repo's npm closure from this repo's
  CI (plan 145 owns the admin app's own gate).
