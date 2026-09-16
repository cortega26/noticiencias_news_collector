# Plan 110: Source-health visibility + polite collector speed-up

> **Executor instructions**: The breaker already exists — finish its visibility and tune throughput. Do NOT invent a second suppression system; either wire the existing detectors or delete the dead code with justification. Update the `110` row in `plans/README.md` when complete.
>
> **Drift check (run first)**:
> `git diff --stat HEAD -- news_collector/collectors/ news_collector/storage/source_repository.py news_collector/monitoring/ news_collector/system/source_health.py news_collector/serving/api.py config.toml`.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MEDIUM (crawl politeness; keep domain delays)
- **Depends on**: None; Wave 1 — parallel-safe with 109 (disjoint files)
- **Category**: efficiency/reliability
- **Planned at**: backend `9fa77b6`, 2026-09-16

## Why this matters

Dead sources waste retries and pollute logs while operators learn about outages from noise. The building blocks all exist but the picture is split: `SourceRepository` auto-cools down, `source_health.py` exports per-run JSON, yet `monitoring/detectors.py + canary.py + AutoSuppressionManager` are referenced only by monitoring internals and tests — never by runtime. Meanwhile throughput is capped at `max_concurrent_requests=1` with 60s penalized-domain delays.

## Current state (verified)

- `storage/source_repository.py:21-114`: 3 consecutive failures → COOLDOWN (`circuit_breaker_max_failures/cooldown_hours`, `force_cooldown_until` for 429s); `models.py:406 consecutive_failures`.
- `system/source_health.py:37-280` + `contracts/source_health.py`: `SourceHealthRecord`, 9-value `failure_taxonomy`, 4 `operational_state`s; `system/reporter.py:89-101` writes `data/exports/source_health.json`.
- `monitoring/detectors.py:54-58` (`consecutive_failure_threshold=3`), `canary.py:16-92` (`AutoSuppressionManager`), `reporting.py:37-113` — not imported by collector/system/storage runtime (only tests + `__init__`).
- `serving/api.py:1227-1242` `GET /v1/admin/sources/health` reads the export (`[]` when missing); consumers `apps/admin/lib/api.ts:208`, `admin_panel.py:568-572`.
- Limits: `config.toml [collection]` + `[rate_limiting]` domain overrides (phys/medicalxpress/techxplore 60s, arxiv 20s, reddit 30s); `[llm_rate_limiting]` circuit `threshold=3/cooldown=60`.

## Scope

**In scope**: surface `COOLDOWN/until` + taxonomy + operational_state in the admin health endpoint and Astro Sources page; resolve the detectors/canary wiring gap (wire OR remove with recorded rationale — no third state); raise `max_concurrent_requests` 1→3 keeping per-domain delays; record before/after `make perf`.

**Out of scope**: changing delay values for penalized domains, new suppression semantics, scheduler changes.

## Steps

### Step 1: Health visibility
Extend the admin health read path to include cooldown state, `force_cooldown_until`, taxonomy, and operational_state from the existing repository/export (no new schema unless a migration is truly needed — prefer reading what exists).

**Verify**: admin Sources page shows a cooled-down source distinctly from healthy; boundary tests; `make test-boundaries`.

### Step 2: Detectors/canary resolution
Either import the existing `SourceOutageDetector/CanaryRunner/AutoSuppressionManager` into the real reporting path with tests, or delete the dead wiring and record why `source_health.py` is the single owner. Partial wiring is forbidden.

**Verify**: `grep -r AutoSuppressionManager|CanaryRunner news_collector --include=*.py` shows a runtime importer outside monitoring/tests, or the symbols are gone with rationale; `make test` green.

### Step 3: Concurrency 1→3 + perf proof
Raise the limit, keep domain overrides, run the perf gate before/after and record numbers in the close-out note.

**Verify**: `make perf` exit 0 (or clean SKIPPED), numbers recorded; `make lint && make type && make test` green.

## Verification (full gate)

| Purpose | Command | Expected |
|---|---|---|
| Ledger | `.venv/bin/python scripts/validate_plans_ledger.py` | OK |
| Baseline | `make lint && make type && make test` | exit 0 |
| Boundaries | `make test-boundaries` | exit 0 |
| Perf | `make perf` | exit 0 or clean SKIPPED, before/after recorded |

## STOP conditions

- STOP if raising concurrency violates per-domain politeness or degrades perf — revert to 1 and record evidence.
- STOP if a schema migration is needed for visibility — re-scope explicitly before writing any migration.

## Git workflow

- Branch: `advisor/110-source-health-visibility`.
- Commit example: `feat(collectors): surface cooldown state and raise fetch concurrency`.
