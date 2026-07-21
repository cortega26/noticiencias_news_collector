# Plan 026: Pin every backend GitHub Action to an immutable commit

> **Executor instructions**: Resolve each tag to an audited upstream commit; never invent hashes. Update plan 026 after the repository-wide assertion passes.
>
> **Drift check (run first)**: `git diff --stat e43bd30..HEAD -- .github/actions .github/workflows .github/dependabot.yml`

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: backend `e43bd30`, 2026-07-21

## Why this matters

All external backend Actions use mutable major tags, including workflows with repository, PR, package, and security-event write permissions. A compromised or retargeted tag would execute with those credentials. The sibling frontend demonstrates the required convention: full 40-character SHA plus a release-tag comment.

## Current state

- `.github/workflows/manual-lock-sync.yml:15-29` grants contents/PR write and uses mutable checkout/setup tags.
- `.github/workflows/release.yml:9-36` grants contents/packages write and uses mutable checkout/github-script tags.
- `.github/actions/setup-python-env/action.yml:18-24` embeds mutable actions used by most jobs.
- A repository scan finds no external `uses:` reference pinned to a 40-character commit.
- `.github/dependabot.yml:18-29` already enables monthly GitHub Actions updates.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Inventory | `rg -n '^\s*uses:' .github` | every external action shows a 40-char SHA |
| Assertion | `rg -n '^\s*uses:\s+[^./][^@]*@(?![0-9a-f]{40})(\S+)' .github --pcre2` | no output |
| YAML sanity | `.venv/bin/python -c "import pathlib,yaml; [yaml.safe_load(p.read_text()) for p in pathlib.Path('.github').rglob('*.yml')]"` | exit 0 |

## Scope

**In scope**: every external `uses:` in `.github/actions/**` and `.github/workflows/**`, comments identifying human-readable versions, and Dependabot config if needed.

**Out of scope**: changing workflow behavior, permissions, triggers, third-party action vendors, or pinning local `./.github/actions/...` references.

## Git workflow

- Branch: `advisor/026-pin-github-actions`
- Commit example: `chore(ci): pin actions to immutable shas`.

## Steps

### Step 1: Build the complete action inventory

List unique `owner/repo@tag` references and the workflows/permissions using them. Resolve the currently intended release tag to its official commit SHA from the upstream repository or GitHub release metadata.

**Verify**: inventory count equals the unique external references from `rg`.

### Step 2: Pin without behavioral upgrades

Replace each mutable tag with the exact commit for the same release, retaining `# vX.Y.Z` comments. Do not combine this supply-chain hardening with major version upgrades.

**Verify**: the negative-lookahead assertion returns no matches; YAML parses.

### Step 3: Preserve controlled update automation

Confirm Dependabot continues proposing GitHub Action SHA updates and that comments remain useful. Add a lightweight CI/repository test that rejects future mutable external refs.

**Verify**: the assertion test itself fails against a temporary mutable fixture and passes on the repository.

## Test plan

- Repository-wide external-action inventory and immutable-SHA assertion.
- Positive fixtures for external pins/local actions and negative fixtures for tag/branch/short-SHA references.
- YAML parse plus existing workflow static/contract tests.
- Review a representative Dependabot SHA update to prove the version comment/update path remains usable.

## Done criteria

- [ ] Every external Action is pinned to 40 hexadecimal characters.
- [ ] Each pin retains a human-readable version comment.
- [ ] No trigger, permission, or step behavior changed.
- [ ] YAML and the immutable-reference assertion pass.

## STOP conditions

- Stop if a tag cannot be mapped to an authoritative upstream commit.
- Stop if the intended tag moved since prior use; report it as a potential supply-chain incident before choosing a hash.

## Maintenance notes

Review Dependabot Action updates like dependency upgrades: verify the new SHA belongs to the stated release and inspect upstream release notes before merging.
