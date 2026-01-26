# Security Policy

## Reporting a Vulnerability

Please report vulnerabilities to the Maintainers/Security Team.

## Dependency Management & Audits

This project maintains strictly isolated environments to prevent supply-chain risks.

### Production (`requirements.lock`)

- **Strict Gate**: `make security`
- **Policy**: Must pass with **ZERO** ignores. No high/critical vulnerabilities allowed in runtime dependencies.

### Development & Refinery (`requirements-security.lock`, `requirements-refinery.lock`)

- **Audited Gate**: `make security-dev`
- **Policy**: Tooling dependencies must also be secure. Exceptions are allowed ONLY if:
  1. The vulnerability is unreachable in production.
  2. No fix is available.
  3. The exception is explicitly documented below with an expiry date.

### Current Exceptions

| Package    | Vulnerability ID      | Scope        | Expiry         | Reason                                                                                                                                                                                                   |
| :--------- | :-------------------- | :----------- | :------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `protobuf` | `GHSA-7gcm-g887-7qv7` | Dev/Refinery | **2026-03-01** | Denial of Service risk. Unreachable in production (protobuf is dev-only dependency via `semgrep` and `streamlit`). Blocked on upstream fixes in tooling ecosystem. Tracked in internal security backlog. |

## Environment Isolation

- **Production**: Main application dependencies (`.venv`).
- **Refinery**: Admin panel dependencies (`.venv-refinery`), physically isolated to prevent "heavy" or permissive libs from leaking into production.
