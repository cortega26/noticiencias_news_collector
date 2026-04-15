# ADR-0002: Hash-pinned dependency lockfiles with --require-hashes

- **Date**: 2024-01-01
- **Status**: Accepted

## Context

The collector runs scheduled jobs that fetch and enrich live news content. A
supply-chain attack targeting any unpinned transitive dependency could silently
corrupt published article data or exfiltrate API keys. Standard `requirements.txt`
with version ranges does not guard against this.

## Decision

All production, security, and refinery dependencies are locked in separate files
(`requirements.lock`, `requirements-security.lock`, `requirements-refinery.lock`)
generated with `pip-compile --generate-hashes`. Bootstrap and CI use
`pip install --require-hashes` so pip rejects any package whose hash does not match
the lockfile, even if the version number is unchanged.

Separate lock files for separate environments keep the security surface of each
venv minimal.

## Consequences

- Dependency upgrades require an explicit `pip-compile` run and a reviewed PR.
- No silent version drift between developer machines and CI.
- `make bootstrap` is fully deterministic and idempotent (stamp-guarded).
- Renovate or Dependabot PRs are the intentional upgrade path, not ad-hoc installs.

## Alternatives considered

| Option | Reason rejected |
|--------|-----------------|
| `requirements.txt` with `==` pins (no hashes) | Protects against version drift but not hash tampering |
| Poetry / PDM lockfile | Migration cost; pip-compile integrates cleanly with existing Makefile and CI |
| Docker only | Useful for deployment but does not help developers running tests locally |
