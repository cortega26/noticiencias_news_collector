# Plan 098: Wire `make audit-placeholders` to the real placeholder gate (or remove it)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat e77a039..HEAD -- Makefile CONTRIBUTING.md docs/placeholder_policy.md .github/workflows/placeholder-audit-pr.yml`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `e77a039`, 2026-09-16

## Why this matters

`CONTRIBUTING.md` tells every contributor to run `make audit-placeholders`
before a PR, but that target is an empty no-op — it prints nothing, checks
nothing, exits 0. Contributors get silent success and push TODOs missing the
required owner/due/issue metadata, which the real diff-aware gate
(`audit-todos-check`) then catches late in CI. One alias (or one deletion)
closes the gap between documented process and actual process.

## Current state

The relevant files, each with one line on its role:

- `Makefile` — empty target (lines 397-398) vs real gates (lines 320-340)
- `CONTRIBUTING.md` — instructs the no-op (lines ~52-54)
- `docs/placeholder_policy.md` — documents only the real gates (~lines 112-117)

Excerpts of the code as it exists today:

`Makefile:397-398`:

```make
.PHONY: audit-placeholders
audit-placeholders:
```

`Makefile:320-340` — the real implementations (`audit-todos` full scan,
`audit-todos-check` PR-scoped with `--pr-diff-only`, SARIF + comment
artifacts, `PLACEHOLDER_BASE` detection at lines 39-46).

`CONTRIBUTING.md:52-54` (approx):

```markdown
- Before sending a PR run the diff-aware audit to catch missing metadata:
  ```bash
  make audit-placeholders
  ```
```

`docs/placeholder_policy.md:112-117` — documents `make audit-todos-check` /
`make audit-todos`, never `make audit-placeholders`.

Repo conventions that apply here:

- Placeholder policy requires owner/due/issue metadata on every production TODO/FIXME; the PR workflow (`placeholder-audit-pr.yml`) enforces it remotely.
- Docs follow code: whichever target survives, `CONTRIBUTING.md` + policy doc must agree in the same change.

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Install   | `make bootstrap`         | declared   | exit 0 |
| Lint      | `make lint`              | declared   | exit 0 |
| Docs gate | `make docs-check`        | declared   | exit 0 |

## Scope

**In scope** (the only files you should modify):

- `Makefile` (`audit-placeholders` target only)
- `CONTRIBUTING.md` (the audit step only)
- `docs/placeholder_policy.md` (only if it needs a one-line alias note)

**Out of scope** (do NOT touch, even though they look related):

- The placeholder audit implementation (`tools/placeholder_audit.py`, real targets, CI workflows).
- Any other empty `.PHONY` targets — report them if found, don't bundle.

## Git workflow

- Branch: `advisor/098-audit-placeholders-alias`
- Conventional commits, e.g. `fix(dx): wire audit-placeholders to the real gate`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `Install`, then `Lint` on the unmodified checkout. Confirm the no-op:
`make audit-placeholders; echo "exit=$?"` → prints nothing, exit 0. Also check
whether `.github/workflows/placeholder-audit-pr.yml` or any script references
`audit-placeholders` (if CI calls it, aliasing changes CI behavior — read first).

**Verify**: no-op confirmed; no hidden callers (or callers listed).

### Step 1: Make it an alias of the diff-aware gate

Replace the empty target with a dependency alias:

```make
audit-placeholders: audit-todos-check ## Alias: diff-aware placeholder audit (CONTRIBUTING entry point)
```

- Keep the `.PHONY` line (update the combined declaration appropriately).
- Do NOT duplicate the recipe — a prerequisite alias means future gate changes propagate automatically.
- If Step 0 found CI calling `audit-placeholders` expecting a no-op (unlikely), STOP and report instead.

**Verify**: `make -n audit-placeholders` shows it resolving to the real gate; `make lint` → exit 0 (tabs check).

### Step 2: Align the docs

1. `CONTRIBUTING.md`: keep the `make audit-placeholders` command (now real) but add the five words "(diff-aware PR gate)" so contributors know what it does; OR point it at `make audit-todos-check` directly and delete the alias — pick one, document the choice in the commit message. (Recommendation: keep the friendly alias name contributors already know; alias it.)
2. `docs/placeholder_policy.md`: one line noting `audit-placeholders` is the contributor alias for `audit-todos-check` — only if the policy doc lists entry points; otherwise skip.

**Verify**: `make docs-check` → exit 0.

### Step 3: Prove it checks something

On the unmodified tree: `make audit-placeholders` → runs the real audit (nontrivial output, exit reflects findings). Then prove it catches: create a scratch branch, add a bare `TODO` (no metadata) to a tracked file, run `make audit-placeholders` → must flag it; delete the scratch change. (Do this verification WITHOUT committing the scratch file.)

**Verify**: flagged-on-purpose TODO is caught; clean tree behaves as the real gate behaves.

## Test plan

- No pytest tests (Make/docs change). Verification: no-op→real-gate behavior proof (Step 3) + `make lint` + `make docs-check`.
- If the repo has a test pinning Make targets (check `tests/` for makefile assertions first — `tools/check_makefile_tabs.py` runs in lint), keep it green.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `make lint`, `make docs-check` exit 0
- [ ] `make audit-placeholders` executes the real diff-aware audit (non-empty output path, finding-reflecting exit code)
- [ ] `CONTRIBUTING.md` describes what the command actually runs
- [ ] A deliberately-bare TODO is caught by the command (demonstrated, then reverted)
- [ ] `git diff --name-only e77a039...HEAD` lists only the in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- A hidden caller depends on `audit-placeholders` being a silent no-op.
- The real gate cannot run locally (missing tool/env) — then aliasing breaks contributors; report instead.
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

- If the placeholder gate is ever renamed, this alias is the single migration point for contributor docs.
- Reviewers: confirm `make help` output still reads sensibly with the alias line.
- **Deferred:** nothing — one alias, one doc line, done.
