# Removal Plan: Protobuf Exception

**Target Vulnerability**: `GHSA-7gcm-g887-7qv7` (protobuf)
**Expiry**: 2026-03-01

## Dependency Chain

The conflicting constraints come from:

1. `semgrep` (Dev Tool) -> pins `protobuf`
2. `streamlit` (Refinery Tool) -> pins `protobuf`

## Removal Checklist

- [ ] Monitor `semgrep` releases for `protobuf` upgrade or unpinning.
- [ ] Monitor `streamlit` releases for `protobuf` upgrade.
- [ ] Once upstream fixes are released:
  - [ ] Run `python scripts/sync_lockfiles.py` to pick up new versions.
  - [ ] Remove `--ignore-vuln GHSA-7gcm-g887-7qv7` from `Makefile` (`security-dev` target).
  - [ ] Remove exception entry from `SECURITY.md`.
  - [ ] Verify `make security-dev` passes cleanly.

## Mitigation

If expiry is reached without upstream fix:

- Evaluate switching to `pipx` for `semgrep` dev tooling to completely remove it from project lockfiles.
- Isolate `refinery` further or accept risk key-holder (admin) tool DoS risk (low severity for internal tool).
