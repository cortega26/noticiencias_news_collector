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
| `make security-dev` | Audits security/refinery locks with a hardcoded protobuf advisory ignore; see expired-policy discrepancy in `SECURITY.md` |

The gate applies scanner-specific severity handling. pip-audit exceptions in
`PIP_AUDIT_ALLOWLIST` require reasons and expiry dates and are checked for
expiration. That enforcement does not cover `security-dev`'s separate CLI ignore.
Mypy is limited to `MYPY_TARGETS` in `Makefile`, not strict checking of all code.

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
