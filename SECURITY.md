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

Every future suppression must enter through `PIP_AUDIT_ALLOWLIST` in
`scripts/security_gate.py` with `reason` + `expires_on` — never as a Makefile
`--ignore-vuln` flag. All pip-audit legs (`quality`, `quality-ci`,
`security`, `security-dev`) evaluate reports through that gate, so every path
enforces the same exception set.

## Implemented allowlist and retired exceptions

As checked on 2026-09-21, `scripts/security_gate.py` contains one exception, for
`GHSA-7gcm-g887-7qv7` (protobuf, dev tooling only) expiring **2026-10-31**. The
script owns its precise rationale and validates expiry. This document records
configured policy; it does not independently verify current upstream fix
availability.

The NLTK exception `GHSA-8mgp-746c-j5xp` (no upstream fix; last affected 3.10.3)
was **retired on 2026-09-21 by removing the dependency**: `nltk` and `textblob`
were declared in `pyproject.toml` but imported nowhere in this repository, so
there was nothing to protect and the exception would otherwise have needed
renewal every month. Their exclusive transitive dependencies (`regex`, `tqdm`,
`defusedxml`) left the locks with them.

The former `make security-dev` inline flag `--ignore-vuln GHSA-7gcm-g887-7qv7`
(protobuf), whose documented authorization expired **2026-03-01**, was retired
on 2026-09-16: the refinery lock already resolves protobuf 6.33.5 (fixed), and
the still-pinned security-lock protobuf 4.25.9 is now an enforced, expiring
`PIP_AUDIT_ALLOWLIST` entry (expires **2026-10-31**, dev-tooling-only DoS risk)
instead of an unexpiring Makefile flag. The prior `make quality` inline flag
`--ignore-vuln CVE-2026-0994` — the same advisory under an alias ID, firing on
no lockfile — was deleted outright. The historical investigation is
`docs/security_removal_plan.md`.

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
