# Open Questions

- Missing: Confirm post-remediation pytest coverage meets ≥80% overall / ≥90% touched modules once scoring tests land (current snapshot 69%).【F:audit/00_inventory.md†L37-L39】【F:audit/06_test_quality.md†L10-L33】
- Missing: Verify Kubernetes or job-runner manifests enforce non-root execution to extend least privilege beyond the container image.【F:audit/07_asvs_checklist.md†L11-L20】
- Missing: Decide on artifact signing approach (e.g., Cosign) for release pipeline hardening.【F:audit/07_asvs_checklist.md†L14-L20】
- Missing: Determine whether CI/doc build should mock heavy dependencies so pre-commit doc generation stays fast.【F:audit/12_dx_checklist.md†L15-L27】
- Missing: Validate GitHub-rendered issue/PR templates match intended formatting (requires portal check).【F:audit/12_dx_checklist.md†L29-L31】

