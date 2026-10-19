# Completed root task queue — archive index (plan 146, 2026-10-19)

Root-level `spec-*.md`/`todo-*.md` pairs were the original task-record convention
(see `docs/AGENTS.md` §0.1). Plan 146 classified every pair that still sat at the
repository root and archived only the **closed** ones, with `git mv` and the
original file names — no content was rewritten or lost.

Classification procedure (from plan 146):

- **closed** — the `todo-*.md` has zero unchecked boxes **and** the work is
  verifiably landed (commit, merged PR, or archived plan).
- **live** — open items remain; the pair stays at the root.
- **unknown** — ownership could not be established; would have been listed
  under "needs an owner". **None were found.**

Counts at classification time: **32 pairs** (`spec-*.md` + `todo-*.md`, excluding
the root `spec.md`/`todo.md` pair itself) → **10 closed and archived** below,
**4 closed but kept at the root** (external references, see below),
**18 live at the root**, 0 unknown.

## Archived closed pairs (10)

| Files (spec + todo) | What it delivered | Evidence |
|---|---|---|
| `spec-collection-recovery-and-scoring.md` + `todo-collection-recovery-and-scoring.md` | Dead collection-run recovery (`worker_pid` stamp + dead-worker reap), per-sub-batch scoring persistence, `validated` intake surface in admin. | `ed328d32` (PR #344); live runs 49–51 |
| `spec-fetch-warning-remediation.md` + `todo-fetch-warning-remediation.md` | Honor `fetch_mode: rss_only` in enrichment routing; split `collector.feed.empty` into `collector.feed.no_new_items`; `sources.yaml` docs. | `35e53b23` (PR #354) |
| `spec-fly-webhook-hosting.md` + `todo-fly-webhook-hosting.md` | Fly.io serving + tunnel deployment (`Dockerfile.serving`, `docker-compose.serving.yml`, `fly-*.toml`) and the 2026-08 production cutover. **Retired 2026-09-26** — both Fly apps destroyed; the configs remain only as rollback fallback (`spec-oci-hosting-migration.md`). | `66664c72` |
| `spec-inventory-baseline-refresh.md` + `todo-inventory-baseline-refresh.md` | Deliberate refresh of `audit/00_inventory.json` closing issue #345 (drift 74 → 0, every changed path mapped to merged PRs). | `34f77dd4` (PR #346) |
| `spec-inventory-self-healing.md` + `todo-inventory-self-healing.md` | `generate_inventory.py --fail-on-drift` gate, `make inventory-refresh`/`inventory-check`, weekly `inventory-autorefresh.yml` healer with semantic (not textual) drift comparison. | `70672157` (PR #348), `0cd5f414` (PR #349) |
| `spec-plans-ledger-hygiene.md` + `todo-plans-ledger-hygiene.md` | `scripts/validate_plans_ledger.py` + tests + `make plans-ledger-check` wiring; ledger/archive reconciliation of DONE plans. | `dd512ba7` |
| `spec-self-healing-publication.md` + `todo-self-healing-publication.md` | Publication repair loop (tag charset `ContentRepair`), publishing-state release on pre-commit failures, live replay of article 2671. | `9b95e34f` (PR #357); frontend `noticiencias#231` |
| `spec-serving-reload-switch.md` + `todo-serving-reload-switch.md` | `SERVING_RELOAD` switch for publication-safe serving sessions. | `ffa2f5e4` (PR #358) |
| `spec-source-alt-extraction.md` + `todo-source-alt-extraction.md` | Source ALT extraction (`og:image:alt` / `twitter:image:alt` / DOM fallbacks, `_clean_alt`); non-blocking follow-up landed separately as the still-live `spec-alt-text-nonblocking.md`. | `c9660b99` (PR #350), `5e164830` (PR #356) |
| `spec-third-party-image-policy.md` + `todo-third-party-image-policy.md` | Third-party source images are not reused as hero images by default (`REMOTE_IMAGE_ALLOWLIST`, `third_party_image_blocked` brief). | `bf2180df` (PR #374) |

## Closed pairs kept at the root (external references)

These pairs have zero unchecked boxes and landed work, but something outside
this plan's write scope cites them at their root path. Moving them would leave a
dangling citation and the citing files (`plans/**`, test code) are owned by other
processes, so they stay in place until those owners update the cites.

| Pair | Cited from |
|---|---|
| `spec-flaky-tests.md` + `todo-flaky-tests.md` | `plans/README.md` (plan 126 entry); `plans/080/tests/phase-1-results.md` |
| `spec-logs-warnings-concurrency.md` + `todo-logs-warnings-concurrency.md` | `tests/test_nvidia_routing_fix.py` (header comment) |
| `spec-nvidia-routing-fix.md` + `todo-nvidia-routing-fix.md` | `tests/test_nvidia_routing_fix.py` (header comment and G6 note) |
| `spec-webhook-inbox-pull.md` + `todo-webhook-inbox-pull.md` | `plans/132-webhook-inbox-poison-row.md`; `docs/RUNBOOK_LOCAL_DEV.md`; `docs/adr/0011-local-publish-hosted-webhook-split.md` |

## Live pairs kept at the root (18)

Unfinished work records with open checkboxes — not scheduled by this plan.

| Pair | Open items |
|---|---|
| `spec-admin-api-surface.md` + `todo-admin-api-surface.md` | 1 |
| `spec-admin-stack-ports.md` + `todo-admin-stack-ports.md` | 2 |
| `spec-alt-text-nonblocking.md` + `todo-alt-text-nonblocking.md` | 1 |
| `spec-editorial-grounding.md` + `todo-editorial-grounding.md` | 2 |
| `spec-editorial-quality-lifts.md` + `todo-editorial-quality-lifts.md` | 2 |
| `spec-internal-review-guardrails.md` + `todo-internal-review-guardrails.md` | 7 |
| `spec-live-publication-progress.md` + `todo-live-publication-progress.md` | 1 |
| `spec-llm-canary.md` + `todo-llm-canary.md` | 1 |
| `spec-llm-health-weights-fix.md` + `todo-llm-health-weights-fix.md` | 3 |
| `spec-llm-provider-chain.md` + `todo-llm-provider-chain.md` | 1 |
| `spec-llm-routing-benchmark.md` + `todo-llm-routing-benchmark.md` | 5 |
| `spec-llm-run-report.md` + `todo-llm-run-report.md` | 1 |
| `spec-oci-hosting-migration.md` + `todo-oci-hosting-migration.md` | 1 |
| `spec-refinery-gui.md` + `todo-refinery-gui.md` | 1 |
| `spec-refinery-gui-phase3.md` + `todo-refinery-gui-phase3.md` | 1 |
| `spec-refinery-gui-phase4.md` + `todo-refinery-gui-phase4.md` | 1 |
| `spec-refinery-gui-phase4-addendum-source-editor.md` + `todo-refinery-gui-phase4-addendum-source-editor.md` | 1 |
| `spec-test-suite-audit.md` + `todo-test-suite-audit.md` | 5 |

## Notes

- The 2026 session log formerly kept in the root `spec.md`/`todo.md` is
  preserved verbatim next to this index as `spec-root-2026-session-log.md` and
  `todo-root-2026-session-log.md`. The root pair is now a thin current-task file
  (per `docs/AGENTS.md` §0.1).
- Plan status lives in `plans/README.md`. New tasks create their `spec.md` +
  `todo.md` (+ `tests/`) inside their own plan folder or plan file — not at the
  repository root.
- `plans/081/tests/inventory.json` is a frozen documentation-audit snapshot
  (2026-10-18) and still lists some moved paths; it is historical evidence, not
  a live index, and was left untouched.
- Files here are historical records: do not rewrite them to describe the
  current system (same rule as `docs/archive/` and `audit/`).
