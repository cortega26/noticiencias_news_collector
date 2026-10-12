# Removal Plan: Protobuf Exception

**Target Vulnerability**: `GHSA-7gcm-g887-7qv7` (protobuf; same advisory as
`PYSEC-2026-1805` / `CVE-2026-0994` — confirmed via pip-audit alias list on
2026-09-16)
**Status (2026-10-12)**: RESOLVED — the `PIP_AUDIT_ALLOWLIST` entry was
removed. The security-lock sync upgraded semgrep 1.121.0 -> 1.180.0, which
pulls opentelemetry-proto 1.37.0 and protobuf 6.33.6 (fixed).
`pip-audit -r requirements-security.lock` reports no known vulnerabilities.
Completing `make security-dev` also required upgrading refinery-lock
tornado 6.5.8 -> 6.5.10 (`GHSA-chx6-46f5-w4vp`, fix 6.5.9; pre-existing on
main 22d3e86, not caused by the protobuf work) — both `security-dev` legs now
report no HIGH findings.

## Dependency Chain

The conflicting constraints come from:

1. `semgrep` (Dev Tool) -> `opentelemetry-proto` (<1.27 pinned `protobuf<5`)
2. `streamlit` (Refinery Tool) -> pins `protobuf`

## Removal Checklist

- [x] Monitor `semgrep` releases for `protobuf` upgrade or unpinning. (2026-09-16: `python scripts/sync_lockfiles.py` re-run → zero diff; security lock still pins protobuf 4.25.9 via the semgrep dev-tool chain.)
- [x] Monitor `streamlit` releases for `protobuf` upgrade. (2026-09-16: refinery lock already resolves protobuf 6.33.5, which carries the upstream fix — no advisory fires there.)
- [x] Once upstream fixes are released:
  - [x] Run `python scripts/sync_lockfiles.py` to pick up new versions. (2026-09-16: done, zero diff.)
  - [x] Remove `--ignore-vuln GHSA-7gcm-g887-7qv7` from `Makefile` (`security-dev` target). (2026-09-16: removed; both `security-dev` locks now evaluated through `scripts/security_gate.py`.)
  - [x] Remove exception entry from `SECURITY.md`. (2026-09-16: drift paragraph replaced with the retired/renewed record.)
  - [x] Verify `make security-dev` passes cleanly. (2026-10-12: tornado 6.5.8 -> 6.5.10 via refinery-lock sync — `scripts/sync_lockfiles.py --upgrade-package tornado`, no blockers needed; `GHSA-chx6-46f5-w4vp` had a 6.5.9 fix. Both `security-dev` legs — security lock and refinery lock — report no HIGH findings; the earlier 2026-09-16 note held only via the then-active allowlist entry.)
- [x] Upgrade security-lock protobuf to 5.29.6+/6.33.5+ via the sync flow once semgrep unpins the range, then delete the `GHSA-7gcm-g887-7qv7` allowlist entry. (2026-10-12: semgrep 1.180.0 requires `opentelemetry-*~=1.37.0`, whose `opentelemetry-proto==1.37.0` requires `protobuf<7.0,>=5.0`. Ran the sync flow (`scripts/sync_lockfiles.py` with the semgrep/OTel/blocker `--upgrade-package` set) → `semgrep==1.180.0`, `opentelemetry-proto==1.37.0`, `protobuf==6.33.6`. `pip-audit -r requirements-security.lock` → no known vulnerabilities. Entry removed from `scripts/security_gate.py`; `PIP_AUDIT_ALLOWLIST` is now empty.)

## Mitigation

If expiry is reached without upstream fix:

- Evaluate switching to `pipx` for `semgrep` dev tooling to completely remove it from project lockfiles.
- Isolate `refinery` further or accept risk key-holder (admin) tool DoS risk (low severity for internal tool).
