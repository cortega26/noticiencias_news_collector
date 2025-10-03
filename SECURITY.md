# Security Overview

This document summarizes the security posture for the Noticiencias News Collector and records any approved suppressions for the automated scanners enforced in CI.

## Threat Model Summary

| Domain | Risks | Mitigations |
| --- | --- | --- |
| **Supply chain** | Compromised dependencies or typosquatted packages pulled during bootstrap. | Locked dependencies (`requirements.lock`, `requirements-security.lock`), `pip install --require-hashes`, weekly dependency reviews, and `pip-audit` gating on every push/PR. |
| **Secret leakage** | Accidental commits of API keys or credentials to Git. | Pre-commit hooks, `.gitleaks.toml` allowlists kept minimal, CI gitleaks scanning with redacted output, and `scripts/run_secret_scan.py` for local sweeps. |
| **Code execution** | Unsafe subprocess calls or unvalidated input leading to arbitrary execution. | CLI arguments validated, subprocess invocations avoid `shell=True`, and Bandit gating on HIGH/MEDIUM findings. |
| **Runtime integrity** | Collector container operating with stale dependencies or silent failure. | Dockerfile pins base image, enforces non-root user, runs healthcheck, and pipelines emit structured logs. |

## Security Tooling & Gates

| Tool | Invocation | Purpose | CI Gate |
| --- | --- | --- | --- |
| Bandit | `bandit -ll -r src scripts` | Detect insecure code patterns (severity >= MEDIUM blocks). | ✅ Required on every push/PR. |
| Gitleaks | `gitleaks detect --redact` | Detect committed secrets (severity defaults to HIGH). | ✅ Required on every push/PR. |
| pip-audit | `pip-audit -r requirements.lock`<br>`pip-audit -r requirements-security.lock` | Check dependencies for known CVEs in runtime and security extras. | ✅ Required on every push/PR. |

The workflow [`Security gates`](.github/workflows/security.yml) runs the commands above and fails on any HIGH or MEDIUM finding. Reports are uploaded to the `security-reports` artifact for triage.

### Running Locally

Before pushing changes, run:

```bash
bandit -ll -r .
gitleaks detect --redact --report-format json --report-path reports/security/gitleaks.json
pip-audit -r requirements.lock --progress-spinner off
pip-audit -r requirements-security.lock --progress-spinner off
```

Reports should be committed only when documenting suppressions.

## Suppression Policy

Suppressing a finding is exceptional and requires:

1. **Code Annotation:** Add an inline comment explaining the business justification (e.g., `# nosec: <reason>` for Bandit) next to the flagged line.
2. **Documentation Entry:** Record the suppression in this section with rationale, owner, and review date.
3. **Issue Tracking:** Link to an open ticket that tracks long-term remediation.

| Tool | Location | Reason | Owner | Review by |
| --- | --- | --- | --- | --- |
| pip-audit | `requirements-security.lock` (jinja2 via trufflehog3) | Upstream `trufflehog3==3.0.10` hard-pins `jinja2==3.1.4`. Gitleaks now covers secret scanning while we track upstream issue. | Security maintainers | 2025-11-03 |

Any temporary suppression must be reviewed within 30 days.

## Incident Response

1. Rotate affected credentials immediately (for leaks).
2. Create an incident note in `reports/security/` with the findings.
3. Notify the `#maintainers-news` channel and open a task referencing the failing workflow run.
4. Patch the vulnerability and re-run the scanners locally before opening a PR.

## References

- [docs/security.md](docs/security.md) – deep-dive policies, access control, and operational runbooks.
- [scripts/security_gate.py](scripts/security_gate.py) – implementation of automated gating.
