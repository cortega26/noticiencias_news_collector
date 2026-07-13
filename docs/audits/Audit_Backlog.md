# Audit Backlog and Roadmap
Last updated: 2026-07-13

## Current status

The authoritative [findings ledger](Findings_Ledger.md) contains F-0001 through
F-0054. Fifty findings are closed. Four dispositions remain active or monitored:

1. **F-0054 (S1, external blocker):** restore GitHub Actions hosted-runner/account
   availability, then rerun the final PR matrix and the branch-equivalent scheduled
   collector.
2. **F-0053 (S1, accepted risk):** remove the dependency-scoped
   `PYSEC-2026-2132` exception by 2026-08-31, or earlier when Semgrep supports
   Click 8.3.3 or later.
3. **F-0042 (S2, partial):** pin actions in `release.yml` and
   `sync-master.yml` through an owner-approved privileged workflow change. The
   connected GitHub policy rejected these two edits; 17 permitted files are pinned.
4. **F-0048 (S2, monitored):** monitor recurring third-party 403 responses before
   changing or disabling source strategy.

## Audit rounds

- **2026-07 Improve Deep — F-0030 through F-0054:** 21 closed, 1 contained with
  expiry, 1 partial, 1 monitored, and 1 external blocker. See
  [2026-07-improve-deep.md](2026-07-improve-deep.md).
- **2026-Q1 (March) — F-0012 through F-0029:** all closed; F-0024 was closed by
  the exclusive-create remediation in F-0039.
- **2026-Q1 (January) — F-0001 through F-0011:** all closed.

Historical remediation materials remain under [remediation](remediation/README.md).

## A7/A8 applicability

- A7 (compliance): defer until enterprise or regulatory requirements apply.
- A8 (FinOps): defer unless cloud spend becomes material.
