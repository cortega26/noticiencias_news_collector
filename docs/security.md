# Security automation overview

The Noticiencias stack runs proactive dependency and source-code scanning so that
high severity risks are surfaced without manual babysitting. This page documents
how the automation behaves and how operators should react when it fires.

## Pull request security gate

The [`Quality (CI)`](../.github/workflows/quality.yml) workflow runs on every push
and pull request. It keeps the following checks blocking merges:

1. `ruff check` — lint and security rules.
2. `mypy` — strict static type checking.
3. `bandit -r news_collector scripts` — source-code security scanner.
4. `pip-audit -r requirements.lock` — dependency vulnerability audit.
5. Semgrep — pattern-based security analysis (`.semgrep.yml`).

The quality gate also runs placeholder auditing via
`placeholder-audit-pr.yml`, with SARIF uploads for CodeQL integration.

Artifacts are uploaded on failure so reviewers can inspect the JSON evidence.
Fix or triage findings locally with `make quality` before retrying the workflow.

## CI security checks

The [`ci.yml`](../.github/workflows/ci.yml) workflow includes dedicated
security steps:

1. **pip-audit**: Audits `requirements.lock` for known vulnerabilities.
   Findings are gated through `scripts/security_gate.py` at HIGH severity.
2. **Bandit**: Scans `news_collector/` and `scripts/` with the project ruleset
   defined in `pyproject.toml`.
3. **Semgrep**: Runs `.semgrep.yml` rules; non-blocking on finding.
4. **Gitleaks**: Secret scanning via `.gitleaks.toml`.

The helper script [`scripts/security_gate.py`](../scripts/security_gate.py) enforces
a **HIGH** severity threshold. If any scanner reports a HIGH (or higher) finding,
the workflow exits non-zero and the GitHub status is marked as failed. Address the
finding, regenerate the reports locally with `make quality`, and re-run the
workflow.

## Vulnerability allowlist

The security gate maintains a time-limited allowlist in
`scripts/security_gate.py` (`PIP_AUDIT_ALLOWLIST`). Each entry requires an expiry
date. Expired entries cause the gate to fail closed. Currently allowed advisories
are limited to packages awaiting upstream fixes that cannot be upgraded in the
current cycle.

### Dependency monitoring

Automated dependency updates are configured through
[Dependabot](../.github/dependabot.yml). Every Monday it scans:

- Root `requirements*.lock` files and `pyproject.toml` build metadata.
- GitHub Actions references.

Dependabot raises `chore:`-prefixed pull requests; the CI pipeline validates
compatibility before merging.

## Auditing and reporting

- **Placeholder audit**: `placeholder-audit-pr.yml` and `placeholder-audit-nightly.yml`
  scan for TODO/FIXME patterns and upload SARIF reports.
- **Audit inventory**: `audit-inventory-weekly.yml` runs a weekly sweep of source
  reliability.

## Responding to alerts

1. Download the latest security artifacts from the failing workflow run.
2. Prioritize HIGH severity items. Use the JSON payload to locate the vulnerable
   package, file, or secret.
3. Implement the fix (upgrade dependency, suppress false positive in
   `.gitleaks.toml`, or remediate vulnerable code).
4. Run `make quality` locally to confirm the pipeline passes.
5. Push the fix and re-run the workflow to clear the alert.

## SSRF and DNS rebinding

Outbound HTTP clients validate every requested URL, including redirect targets,
before sending the request. Validation permits only HTTP and HTTPS, resolves the
hostname, rejects resolution failures, and blocks private, loopback, link-local,
reserved, and otherwise non-global IP addresses.

The current clients do not pin the validated IP address to the subsequent network
connection. DNS can therefore change between validation and connection, leaving a
residual DNS-rebinding window. Closing that window requires transport-specific
adapters for both `requests` and `httpx` that preserve the original hostname for
HTTP `Host` headers and TLS SNI while connecting to a validated address.

Production deployments should enforce outbound network policy: deny access to
private and link-local ranges, block cloud metadata endpoints such as
`169.254.169.254`, and allow only required destination ports and networks.
Application validation is defense in depth, not a replacement for egress controls.
