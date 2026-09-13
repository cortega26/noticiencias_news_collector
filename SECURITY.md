# Security policy

Report vulnerabilities privately to the repository maintainers/security team.
Do not include credentials or sensitive report payloads in a public issue.

## Checks and exception policy

`make security` audits application dependencies and source; `make security-dev`
audits tooling and legacy Refinery environments. See `docs/security.md` for
actual gate behavior. Environment isolation reduces dependency coupling; it
does not itself prevent supply-chain compromise.

High-severity risks require a fix or an explicit, time-limited exception with
scope, exposure rationale, owner and expiry. Do not silently extend an expired
exception or infer safety from an ignored scanner finding.

## Implemented allowlist and policy discrepancy

As checked on 2026-09-04, `scripts/security_gate.py` contains an exception for
`GHSA-8mgp-746c-j5xp` expiring **2026-09-30**. The script owns its precise
rationale and validates expiry. This document records configured policy;
it does not independently verify current upstream fix availability.

`make security-dev` still passes `--ignore-vuln GHSA-7gcm-g887-7qv7` for
protobuf. Its previously documented authorization expired **2026-03-01**,
and that Make recipe does not enforce expiry. This is unresolved policy/code
drift, not a renewed exception. Re-audit the resolved tooling locks and remove
the obsolete ignore, or obtain an explicit reviewed exception if still needed.
The historical investigation is `docs/security_removal_plan.md`.

The former NLTK exception `GHSA-7p94-766c-hgjp` expired **2026-04-15** and is
not the current scripted allowlist entry. Old statements that version 3.9.2
was the latest available release are historical, not upgrade guidance.

## Environments

- `.venv`: backend application and quality tooling installed by bootstrap.
- `.venv-refinery`: legacy Streamlit dependencies.
- `apps/admin/`: current Astro admin with its own npm dependency graph.

Check the lockfile relevant to the deployed artifact. A development dependency
or client-side `PUBLIC_*` variable must not be described as protected merely
because it is outside the application lockfile or stored in an environment file.
