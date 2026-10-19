# Plan 144: Pin the dev toolchain and make lock/venv drift loud

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 1ff6926..HEAD -- Makefile .pre-commit-config.yaml .github/workflows/ci.yml .github/actions/setup-python-env docs/ci.md scripts/ requirements-security.lock`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S-M
- **Risk**: LOW-MED (aligning black/ruff to the hook revisions can cause a
  one-time formatting diff)
- **Depends on**: plan 143 first (it touches the same lock/venv area), then this;
  **sequence against plans 138/139/142/145** for the shared Makefile/CI files
- **Category**: deps / dx
- **Planned at**: commit `1ff6926`, 2026-10-18

## Why this matters

Two "the environment is not what it says" defects:

1. **The gate toolchain is unpinned.** `$(BOOTSTRAP_STAMP)` installs
   `ruff mypy black "isort==5.13.2" pre-commit pdoc types-requests … semgrep`
   with no versions, so the local gate tools drift from the pre-commit pins that
   decide what "clean" means at commit time. Measured today: `ruff 0.15.22` vs
   the hook's `v0.14.14`; `black 26.5.1` vs `26.1.0`; `pdoc 16.0.0` vs
   `15.0.4`. Plan 129 already paid for exactly this class of bug once (unpinned
   `isort` canonicalizing imports differently from the hook). A green local gate
   and a red hook — or the reverse — decided by install date is a defect.
2. **The security lock is installed over the runtime lock into the same venv.**
   `Makefile`'s bootstrap installs `requirements.lock` and then
   `requirements-security.lock` into `$(VENV)`. Four packages collide and the
   second install wins: click `8.5.0`→`8.4.2`, pyee `13.0.0`→`13.0.1`,
   smmap `5.0.3`→`5.0.2`, types-requests `2.33.0.20260712`→`2.32.4.20260107`
   (confirmed by `pip list` and by grepping the two locks). Nothing compares the
   environment to the lock, so a future "lock says X, tests pass on Y" defect is
   unattributable. `Dockerfile.serving` installs only `requirements.lock`, so the
   *runtime truth* is the lock, not the venv.

The physical one-venv-per-lock split is **deferred** (Step 3) because it touches
the CI cache action; Steps 1-2 close the truthfulness gap cheaply.

## Current state

- `Makefile:3-30` — variables: `VENV ?= .venv`, `VENV_REFINERY ?= .venv-refinery`,
  `RUFF := $(PYTHON_BIN) -m ruff`, `BLACK`, `ISORT`, `PDOC`, `PIP_AUDIT`,
  `BANDIT`, `SEMGREP`, `PRE_COMMIT`.
- `Makefile` `$(BOOTSTRAP_STAMP)` recipe (the `pip install` block, around
  `:78-82`) — installs the runtime lock, then the security lock, then the
  unpinned tool list.
- `.pre-commit-config.yaml` — the pins: ruff `v0.14.14`, black `26.1.0`, isort
  `5.13.2`, bandit `1.7.9`, `pdoc==15.0.4` (in the local hook's
  `additional_dependencies`), mypy via `.venv/bin/python -m mypy` (no pin).
- `.github/workflows/ci.yml:27` (and the sibling jobs) — the venv cache key is
  `hashFiles('requirements.lock','requirements-security.lock')`; a cached job
  keeps whatever the unpinned install resolved that day.
- `.github/actions/setup-python-env/` — the shared setup action.

## Commands you will need

| Purpose              | Command                                                       | Provenance | Expected on success              |
|----------------------|---------------------------------------------------------------|------------|----------------------------------|
| Install/baseline     | `make bootstrap`                                              | declared   | exit 0                           |
| Tool versions (today)| `.venv/bin/ruff --version; .venv/bin/black --version; .venv/bin/pdoc --version; .venv/bin/python -m mypy --version` | executed | shows the drift described above |
| Lint                 | `make lint`                                                   | declared   | exit 0                           |
| Types + coverage     | `make type`                                                   | declared   | exit 0                           |
| Unit suite           | `make test`                                                   | declared   | all pass                         |
| New gate             | `make toolchain-check`                                        | declared   | exit 0, prints each tool version |
| New gate             | `make lock-parity-check`                                      | declared   | exit 0                           |
| Ledger               | `make plans-ledger-check`                                     | declared   | `validate_plans_ledger: OK`      |

Provenance: the versions row was measured by the advisor in this session; the
rest are `declared`.

## Scope

**In scope**:

- `Makefile` — the bootstrap tool install, two new check targets, and
  `verify-ci`'s composition
- `.pre-commit-config.yaml` — only if a pin must move (prefer moving the venv to
  the hook, not the reverse; if you move a pin, say why)
- New: `scripts/check_toolchain.py`, `scripts/check_lock_parity.py`
- `docs/ci.md` — the two new gates
- `tests/` — unit tests only if the scripts warrant one (they are small; a
  self-check is acceptable)

**Out of scope** (do NOT touch):

- The three lockfiles' contents.
- `pyproject.toml`'s tool configuration.
- The security venv split (deferred — see Step 3).
- `requirements-refinery.lock` handling.

## Git workflow

- Branch: `advisor/144-toolchain-and-lock-truth`
- Conventional commits, e.g. `chore(dx): pin gate tools to the hook revisions (plan 144)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `make bootstrap`, `make lint`, `make type`, `make test`. Record the tool
versions (the `executed` row). Red baseline → STOP and report.

**Verify**: every command matches its expected result; the drift table is recorded.

### Step 1: Pin the venv toolchain to the hook pins

1. Write `scripts/check_toolchain.py`: parse `.pre-commit-config.yaml`, map the
   hook repos to module names (ruff, black, isort, bandit), read their `rev`
   (strip a leading `v`), read `pdoc==X` from the pdoc hook's
   `additional_dependencies`, and compare with the installed versions
   (`importlib.metadata.version`). For `mypy` there is no hook pin — pin it in
   this script as an explicit constant with a comment that raising it is a
   deliberate change. Exit 1 with a table on mismatch, 0 otherwise.
2. Change the bootstrap install list to install those exact versions, reading
   nothing dynamically: write the versions literally in the Makefile, and let
   `toolchain-check` fail if they drift from the hooks. Add a comment above the
   line pointing at the checker (single source of truth = `.pre-commit-config.yaml`).
3. Add `Makefile` target `toolchain-check` (`@$(PYTHON_BIN) scripts/check_toolchain.py`)
   and add it to `verify-ci`.
4. Reinstall the pinned tools and fix any resulting lint/format diff:
   `.venv/bin/python -m pip install` the pinned versions, then `make lint`. If
   ruff/black at the pinned versions reformat files, commit that reformat as a
   separate, clearly-labelled commit (`style: align with pinned formatter versions`)
   and report the file count — this is expected once.

**Verify**: `make toolchain-check` exits 0; `make lint` exits 0; the venv
versions equal the hook revisions.

### Step 2: Make lock/venv drift loud

5. Write `scripts/check_lock_parity.py`:
   - read `requirements.lock` (name==version pairs) and the venv's
     `pip list --format=json` (or `importlib.metadata`);
   - assert every runtime pin is installed at the pinned version **except** a
     dated exception map that names exactly the known collisions
     (click, pyee, smmap, types-requests) with a one-line reason
     ("security lock overrides it at bootstrap; see plan 144 deferral");
   - fail on any new mismatch or missing package.
   - Keep it dependency-free (stdlib + the venv).
6. Add `Makefile` target `lock-parity-check` and add it to `verify-ci`.
7. Document both gates in `docs/ci.md` (one line each) and, in the script's
   docstring, how to heal a red result (`make bootstrap` after a lock change).

**Verify**: `make lock-parity-check` exits 0 today; then temporarily install a
different version of a small runtime pin in a scratch venv copy (or simulate by
pointing the script at a doctored lock in `/tmp`) and confirm it exits 1 naming
the package.

### Step 3: Scope the physical split (report, do not build)

8. Write a short section (10-20 lines) at the end of this plan file under
   `## Execution record` stating: what a `.venv-security` split would touch
   (`Makefile` variables `PIP_AUDIT`/`BANDIT`/`SEMGREP`, `bootstrap`, `security`,
   `security-dev`, `quality*`, `.github/actions/setup-python-env/action.yml`'s
   cache key + install step, `docs/ci.md`), the expected benefit (the venv
   matches the lock exactly), and why it is deferred (CI cache/venv-provisioning churn vs. the
   parity check already catching new drift). Do **not** implement it.

**Verify**: the section exists; no other files changed in this step.

## Test plan

- `scripts/check_toolchain.py` and `scripts/check_lock_parity.py` are self-checking
  gates; if unit tests exist for sibling tooling scripts
  (e.g. `tests/test_scan_placeholders.py`), add one small test per script that
  runs it against a fixture and asserts exit codes. Otherwise record that the
  scripts are covered by their Make targets and say so.

**Verify**: `make test` → green; `make verify-ci` → green (it now runs both gates).

## Done criteria

All must hold:

- [ ] `make lint`, `make type`, `make test` exit 0
- [ ] `make toolchain-check` and `make lock-parity-check` exit 0 and are in `verify-ci`
- [ ] Installed ruff/black/isort/bandit/pdoc versions equal the hook pins (recorded table)
- [ ] The parity script fails on an injected mismatch (proven)
- [ ] The deferred-split section is written in `## Execution record`
- [ ] `make inventory-refresh` run if new top-level files/Make targets were added; `make inventory-check` exits 0
- [ ] `git diff --name-only main...HEAD` lists only in-scope files (+ inventory baseline)
- [ ] `plans/README.md` row 144 updated; `make plans-ledger-check` → OK

## STOP conditions

- Aligning to the pinned versions breaks a gate in a way that is not a pure
  formatting diff (e.g. a new ruff rule fails) → report the rule and the files;
  do not add `--no-fix`-style suppressions without a stated reason.
- `.pre-commit-config.yaml` pins cannot be resolved from the registry in the
  executor's environment → report; do not substitute nearby versions.
- The parity script cannot distinguish "deliberately overridden" from "broken"
  without a fragile heuristic → prefer a smaller script over a clever one and say
  so in the STOP report.

## Maintenance notes

- `.pre-commit-config.yaml` becomes the single source of truth for tool versions;
  any pin bump must be accompanied by a bootstrap line change and a
  `toolchain-check` run.
- Reviewer should scrutinise: the one-time formatting commit (is it purely
  mechanical?), and that the parity script's exception list is dated and
  minimal.
- **Deferred:** the physical `.venv-security` split, recorded in
  `## Execution record`. Unblocked by a decision about CI cache cost; the parity
  check keeps drift visible meanwhile.

## Execution record

### Deferred: the physical `.venv-security` split

`make bootstrap` installs `requirements-security.lock` over `requirements.lock`
into the same venv, so four runtime pins are shadowed (click, pyee, smmap,
types-requests; see `scripts/check_lock_parity.py`). A physical split would touch:

- `Makefile` — a `VENV_SECURITY` variable, `PIP_AUDIT`/`BANDIT`/`SEMGREP`,
  `bootstrap` plus a new `bootstrap-security` stamp, `security`, `security-dev`, `quality*`.
- `.github/actions/setup-python-env/action.yml` — the `.venv` cache path/key
  (`hashFiles('requirements.lock','requirements-security.lock')`) and install step.
- `.github/workflows/{quality,ci}.yml` — cache restore order and jobs expecting
  security tools in `.venv`; `docs/ci.md` — the second environment and its parity gate.

Benefit: the runtime venv matches `requirements.lock` exactly (what
`Dockerfile.serving` installs), the four-entry exception map disappears, and
`make lock-parity-check` can become a strict equality check.

Deferred because: second-venv CI cache/provisioning churn vs. a divergence that
`make lock-parity-check` now makes loud and enumerable. The durable
`mcp`/semgrep decoupling (semgrep's exact pin holds `mcp` in the security lock)
still needs its own plan.
