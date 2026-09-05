# Plan 078 — Reap expired leases on start(), not only at boot

## Resolved nuance (caught by the concurrent tests before merge)

`running` + NULL heartbeat is NOT unconditionally stale: a live run has
no heartbeat for ~60s after transitioning (first beat lands one interval
in). Reaping it would murder a live run AND break single-flight (both
202s instead of 202+409 — observed live in CI). Rule finally shipped:

- running + heartbeat older than lease → reap everywhere;
- running + NULL heartbeat → reap only if started_at is lease-old;
- queued → reap only at boot (`include_queued=False` in `start()`).
Heartbeat is 60s vs 3600s lease, so the margins are wide.

## Incident (run 20, 2026-09-04)

Run 20's owner process died at a 23:11 UTC server restart with the last
heartbeat at 22:35. Lease timeout is 3600s, so the boot-time recovery
left the row `running`. Result: a stale-running row that (a) shows a
live run in the UI/API that will never finish, and (b) 409-blocks every
new publish via single-flight ("already running" pointing at a dead
run) — the user's "doesn't seem to be working". Only another restart
past the lease expiry would have cleared it. Fixed manually this time
(row 20 → interrupted, documented in error_detail).

## Design

Call the existing `recover_expired_leases()` at the top of `start()`
(publication AND collection — identical structure, identical deadlock;
collection's own recover method already exists) before the queued
INSERT. Only rows older than the lease timeout are touched, so a
genuinely live run (heartbeating every interval ≪ timeout) is never
affected; the partial unique index still guards true races.

Non-goals: changing the 3600s lease (conservative is correct for slow
hosts), touching heartbeat cadence, backfilling history.

## Verification

- Tests: stale running row auto-recovers on next start (new run
  starts instead of 409); live row (fresh heartbeat) still 409s;
  collection mirror.
- `make lint && make type && make test && make test-boundaries`.
