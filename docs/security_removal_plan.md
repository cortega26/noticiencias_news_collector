# Removal Plan: Protobuf Exception

**Target Vulnerability**: `GHSA-7gcm-g887-7qv7` (protobuf; same advisory as
`PYSEC-2026-1805` / `CVE-2026-0994` — confirmed via pip-audit alias list on
2026-09-16)
**Status (2026-09-16)**: inline Makefile flags removed; residual security-lock
exposure tracked as an enforced `PIP_AUDIT_ALLOWLIST` entry expiring
2026-10-31. Refinery lock already fixed (protobuf 6.33.5).

## Dependency Chain

The conflicting constraints come from:

1. `semgrep` (Dev Tool) -> pins `protobuf`
2. `streamlit` (Refinery Tool) -> pins `protobuf`

## Removal Checklist

- [x] Monitor `semgrep` releases for `protobuf` upgrade or unpinning. (2026-09-16: `python scripts/sync_lockfiles.py` re-run → zero diff; security lock still pins protobuf 4.25.9 via the semgrep dev-tool chain.)
- [x] Monitor `streamlit` releases for `protobuf` upgrade. (2026-09-16: refinery lock already resolves protobuf 6.33.5, which carries the upstream fix — no advisory fires there.)
- [x] Once upstream fixes are released:
  - [x] Run `python scripts/sync_lockfiles.py` to pick up new versions. (2026-09-16: done, zero diff.)
  - [x] Remove `--ignore-vuln GHSA-7gcm-g887-7qv7` from `Makefile` (`security-dev` target). (2026-09-16: removed; both `security-dev` locks now evaluated through `scripts/security_gate.py`.)
  - [x] Remove exception entry from `SECURITY.md`. (2026-09-16: drift paragraph replaced with the retired/renewed record.)
  - [ ] Verify `make security-dev` passes cleanly. (2026-09-16: passes via the enforced allowlist entry for the security lock; refinery lock is clean. Remaining work is the upstream upgrade below.)
- [ ] Upgrade security-lock protobuf to 5.29.6+/6.33.5+ via the sync flow once semgrep unpins the range, then delete the `GHSA-7gcm-g887-7qv7` allowlist entry (expires 2026-10-31; the gate fails closed on expiry).

## Mitigation

If expiry is reached without upstream fix:

- Evaluate switching to `pipx` for `semgrep` dev tooling to completely remove it from project lockfiles.
- Isolate `refinery` further or accept risk key-holder (admin) tool DoS risk (low severity for internal tool).
