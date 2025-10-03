# Phase 7 — OWASP ASVS Checklist

## Scope
Assessment targets the headless CLI/data-pipeline deployment model for Noticiencias, covering configuration management, containerization, and CI security automation. Controls unrelated to interactive authentication or session management are out of scope.

## Control Status
| ASVS Control | Description (abridged) | Status | Evidence | Follow-up |
| --- | --- | --- | --- | --- |
| V1.1.1 | Document security architecture, components, and trust boundaries. | ✅ Pass | `AGENTS.md` and refreshed security documentation (`docs/security.md`). | Keep diagrams updated when new pipeline stages ship. |
| V1.2.4 | Ensure automated security testing is integrated into CI/CD. | ✅ Pass | New `audit-security` workflow runs Bandit, Gitleaks, and pip-audit on push/PR. | Monitor runtime to keep job under 5 minutes. |
| V4.1.3 | Enforce least-privilege execution environments. | ✅ Pass | Dockerfile now creates a non-root `app` user before running the collector. | Extend principle to Kubernetes manifests (Missing). |
| V5.1.4 | Validate and sanitize all configuration input. | ✅ Pass | `noticiencias.config_manager` serializes via Pydantic models and drops unset/None values. | Add regression tests for `_serialize_for_toml`. |
| V10.2.1 | Perform static code analysis on all code prior to release. | ✅ Pass | Bandit gate enforced in CI; weekly scheduled scan remains active. | Consider enabling SARIF uploads for code scanning dashboard. |
| V10.4.2 | Maintain a software composition analysis (SCA) process. | ✅ Pass | pip-audit executes on lockfiles (three GHSA IDs suppressed pending upstream `trufflehog3` fix); Dependabot already enabled. | Automate SBOM publication via CycloneDX output (Missing). |
| V13.2.1 | Protect sensitive secrets and keys from source control. | ⚠️ Partial | `.gitleaks.toml` allowlists documented false positives; no secrets in current tree. | Add pre-commit secret hook to shorten feedback loop. |
| V14.2.3 | Ensure secure configuration defaults for all deployments. | ✅ Pass | Hash-locked dependency installs and documented security defaults in README/`docs/security.md`. | Document minimum container runtime permissions (Missing). |

## Open Questions
- Missing: Confirm Kubernetes/job runner manifests drop root capabilities to extend least privilege beyond the container image.
- Missing: Decide on artifact signing strategy (e.g., Cosign) and integrate with release pipeline.
