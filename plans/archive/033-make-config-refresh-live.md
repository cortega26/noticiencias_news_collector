# Plan 033: Make runtime configuration refresh observable by all consumers

> **Executor instructions**: Migrate consumers to one runtime configuration authority and prove values change without process restart. Do not patch individual stale imports. Update plan 033 in `plans/README.md` when complete.
>
> **Drift check (run first)**: `git diff --stat e43bd30..HEAD -- news_collector/config news_collector/collectors news_collector/scoring news_collector/storage news_collector/infrastructure news_collector/enrichment apps/refinery tests`

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: HIGH
- **Depends on**: plans/027-complete-stage4-wiring-and-cache.md
- **Category**: bug
- **Planned at**: backend `e43bd30`, 2026-07-21

## Why this matters

The Refinery advertises live configuration changes, but refresh replaces exported dictionaries while many modules retain objects imported earlier. Operators can save a value successfully yet collectors, scoring, storage, HTTP, and logging continue using stale data until restart. One explicit runtime configuration authority removes split-brain behavior.

## Current state

- `news_collector/config/settings.py:32-35` says compatibility shims resolve live, but `_resolve_builders()` at lines 193-204 assigns replacement dictionaries.
- `news_collector/collectors/base_collector.py:33-39` imports config dictionaries by value at module import time.
- `apps/refinery/admin_panel.py:434-439` saves a configuration then calls refresh, making live application an operator-visible contract.
- Direct config imports also exist in activity monitoring, request/HTTP clients, source/article repositories, enrichment, logging, scorer, RSS/HTML/Reddit collectors, and pipeline paths.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Targeted tests | `.venv/bin/python -m pytest tests/unit/config tests/unit/collectors tests/unit/scoring -q` | all pass, including live-refresh cases |
| Import audit | `rg -n "from news_collector\.config import .*(_CONFIG|ALL_SOURCES|DATABASE)" news_collector apps` | only documented immutable constants or compatibility boundary remain |
| Full tests | `make test` | exit 0 |
| Static checks | `make lint && make typecheck` | exit 0 |

## Scope

**In scope**: runtime configuration facade/snapshot API, refresh operation, every production consumer of mutable configuration, Refinery save/apply feedback, and concurrency/refresh tests.

**Out of scope**: changing config keys/defaults, adding remote configuration, automatically applying values that require resource reconstruction, or refactoring immutable constants.

## Git workflow

- Branch: `advisor/033-live-config-refresh`.
- Commit example: `fix(config): route mutable settings through live snapshots`.

## Steps

### Step 1: Inventory and classify configuration reads

Generate a checked inventory of mutable dictionaries imported into production modules. Classify each value as read-per-operation, snapshot-per-pipeline-cycle, or restart-required resource construction. Add this matrix to `news_collector/config/README.md` or the nearest active config document.

**Verify**: the `rg` result is fully represented in the matrix and tests name at least one consumer in each class.

### Step 2: Introduce one typed runtime snapshot API

In `news_collector/config/settings.py` (or a narrowly named sibling), expose an immutable, versioned `RuntimeConfigSnapshot` and `get_runtime_config()` accessor. Refresh must validate/build a complete new snapshot, then swap one reference atomically. Do not expose nested mutable dictionaries that callers can retain or mutate. Keep compatibility exports only as deprecated read-only proxies while callers migrate.

**Verify**: unit tests show failed validation leaves the old snapshot/version untouched and successful refresh changes version plus values atomically.

### Step 3: Migrate consumers by lifecycle

Replace direct imports in collectors, scoring, enrichment, storage, network clients, monitoring, and logging. Request/cycle code obtains one snapshot at the boundary and passes it down; long-lived resources either rebuild through an explicit hook or report `restart_required`. Avoid reading different config versions halfway through one collection/scoring cycle.

**Verify**: import audit contains no mutable by-value imports; an integration test changes a representative collector limit, scoring value, and HTTP timeout and observes the new value on the next cycle without restart.

### Step 4: Make Refinery application semantics truthful

Return applied version, applied-live fields, and restart-required fields after save. Display failures rather than claiming success. Audit-log the old/new version and changed key paths without secret values.

**Verify**: Refinery tests cover valid live apply, validation failure, restart-required setting, and concurrent reader during refresh.

## Test plan

- Atomic snapshot build/swap, invalid refresh rollback, immutability, and version monotonicity.
- Representative collector/scorer/client consumers use a new snapshot on the next operation.
- A cycle already in progress remains internally consistent.
- Refinery reports exact application state and never logs secret values.

## Done criteria

- [ ] No production module retains a mutable configuration dictionary imported by value.
- [ ] Refresh is atomic, versioned, and rollback-safe.
- [ ] Live versus restart-required settings are explicit to operators.
- [ ] Targeted and full backend validation pass.

## STOP conditions

- Stop if plan 027 has not finalized model selection/cache config access.
- Stop if a long-lived resource cannot be rebuilt safely; mark that key restart-required rather than silently mutating it.
- Stop if the migration requires changing public config key names.

## Maintenance notes

New mutable settings must declare lifecycle semantics and have a live-refresh or restart-required test. Ban new direct imports of mutable config via lint/test.
