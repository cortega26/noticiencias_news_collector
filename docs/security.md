# Security automation

Status: Active. This describes committed automation, not a fresh vulnerability audit.

## Gate ownership

`Makefile`, `.github/workflows/quality.yml`, `scripts/security_gate.py` and
`SECURITY.md` own the implemented checks and exception policy. The main
`.github/workflows/ci.yml` is not a dedicated security-scanner workflow.
GitHub branch protection is external configuration; a workflow being present
does not prove it is required for merge.

| Entry point | Current behavior |
| --- | --- |
| `make security` | pip-audit and Bandit JSON interpreted by `scripts/security_gate.py`; gitleaks only if installed locally |
| `make quality-ci` | Context validation, Ruff, scoped mypy plus coverage tests, Bandit and pip-audit gates; Semgrep `--config auto` is non-blocking |
| `.github/workflows/quality.yml` | Installs gitleaks, runs quality checks and the separate secret scan; uploads reports |
| `make security-dev` | Audits security/refinery locks through the shared `scripts/security_gate.py` policy (`PIP_AUDIT_ALLOWLIST`, reason + expiry enforced), like every pip-audit leg |

The gate applies scanner-specific severity handling. pip-audit exceptions in
`PIP_AUDIT_ALLOWLIST` require reasons and expiry dates and are checked for
expiration. `security-dev` evaluates through that same allowlist; no CLI-level
exception exists. Mypy is limited to `MYPY_TARGETS` in `Makefile`, not
strict checking of all code.

Current exception (2026-10-19): `GHSA-84m7-p3x7-pcfv` for `mcp==1.29.0` is
allowlisted until **2026-11-30**. `mcp` is semgrep 1.180.0's MCP server;
semgrep pins `mcp==1.29.0` exactly (no release through 1.181.0 lifts the pin),
so the advisory's fix versions (1.30.0/2.2.0) are unreachable through
`scripts/sync_lockfiles.py` — the gate correctly failed closed and the operator
chose a bounded exception. It is dev-only: absent from `requirements.lock` and
`requirements-refinery.lock` and from every image. The durable fix (decouple
semgrep from the audited environment) is plan 144; after the expiry the gate
fails closed again by design. `security-dev` runs in
`.github/workflows/quality.yml`, so this exception is exercised by CI instead of
a manual command.

Placeholder audits and inventory workflows are separate automation; see their
YAML and [ci.md](ci.md) for triggers. Dependabot configuration lives in
`.github/dependabot.yml`; it is not a substitute for lockfile audit results.

## Responding to findings

Read the failing scanner report, affected dependency path or source, lockfile
revision and scan date. Reproduce using the relevant check, fix the cause,
and verify the resulting diff. Do not suppress a finding solely to restore
a green check. Historical gitleaks baseline entries do not authorize adding
new secrets. Follow `SECURITY.md` for exception review and reporting.

## Outbound HTTP boundary

The project HTTP clients validate URL schemes, DNS results and redirect
targets to reject non-public destinations. Their validation does not pin the
validated IP to the later connection, leaving a DNS-rebinding window. This
is a known transport limitation, not a claim that every possible outbound
integration is uniformly protected. Review the actual client used by a new
integration and the deployment's egress policy before asserting protection.
