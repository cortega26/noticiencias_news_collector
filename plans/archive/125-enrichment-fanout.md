# Plan 125: Bound enrichment fan-out per article (after pacing lands)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 04016ca..HEAD -- news_collector/collectors/rss_collector.py news_collector/enrichment/router.py news_collector/collectors/base_collector.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: backend plan 116 (per-host pacing for article
  enrichment) — MUST be DONE first. Concurrency against target sites
  without per-host caps risks rate-limit/ban consequences; 116 is the
  pacing control this plan's fan-out runs inside.
- **Category**: perf
- **Planned at**: commit `04016ca`, 2026-10-11
- **Issue**: omit

## Why this matters

Sources run concurrently (semaphore 10), but articles *within* a source
enrich strictly serially through a fully synchronous router — per-source
wall-clock is the sum of per-article fetch+extract latencies, and one slow
source stalls its whole candidate set behind head-of-line blocking. A
bounded fan-out (cap ~4–8, inside plan 116's per-host pacing) multiplies
collection-cycle throughput with per-article error isolation preserved.
Sequencing behind 116 is load-bearing, not bureaucratic: fan-out without
pacing is how you get banned by sources.

## Current state

Facts (verified 2026-10-11):

```python
# rss_collector.py:893-901 — serial per-candidate enrichment
for cand in selected_candidates:
    try:
        cand.setdefault("content_mode", ...)
        enrichment_result = self.router.route_enrichment(
            source_id, source_config, cand
        )
```

```python
# enrichment/router.py:68-570 — route_enrichment is fully synchronous
# (blocking HTTP/headless calls, time.time() durations)
def route_enrichment(self, source_id, source_config, candidate): ...
```

```python
# base_collector.py:193-210 — sources run concurrently (semaphore 10);
# articles within a source do not.
```

Plan 116 (TODO at plan time): per-host pacing for article enrichment.
Check its status row first — if not DONE, this plan WAITS (STOP, see below).

Repo conventions: LAW-B10 (perf-sensitive collector loops reviewed for
repeated work); bounded retries for I/O only; per-item outcomes explicit
(LAW-B6 — the gather must preserve per-candidate fallback/metadata logic
per result, including failures).

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Bootstrap | `make bootstrap`         | declared   | exit 0              |
| Lint      | `make lint`              | declared   | exit 0              |
| Type      | `make type`              | declared   | exit 0              |
| Unit      | `make test`              | declared   | pass                |
| Boundaries | `make test-boundaries`  | declared   | pass                |
| Perf      | `make perf`              | declared   | pass (improvement or parity) |

## Scope

**In scope** (the only files you should modify):

- `news_collector/collectors/rss_collector.py` (bounded dispatch of the
  per-candidate loop)
- `news_collector/enrichment/router.py` (thread-safety of shared
  enrichers/metrics ONLY as needed for the fan-out — minimal, documented)
- `tests/` (fan-out tests: ordering, error isolation, pacing compliance)

**Out of scope** (do NOT touch, even though they look related):

- Per-host pacing policy itself — plan 116 owns it; this plan consumes it.
- Rate-limit values, politeness delays, robots handling — untouched.
- Other collectors' loops (headless/html) — rss path first; others only
  via a follow-up note, not in this diff.
- Async-ifying the router — `asyncio.to_thread` pool or thread executor
  around the sync call; no router rewrite.

## Git workflow

- Branch: `advisor/125-enrichment-fanout`
- Commit in slices (dispatch, then safety fixes if any); e.g.
  `perf(collectors): bound per-article enrichment fan-out`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Gate on plan 116 + baseline

Check `plans/README.md` plan 116 row: if not DONE, STOP and report
(waiting on pacing). If DONE, read its pacing API (cap hooks, per-host
state) — the fan-out MUST route through it, not around it. Profile one
collection cycle on a multi-candidate source; record wall-clock.

**Verify**: 116 DONE and its pacing entry points identified; baseline wall-clock recorded.

### Step 1: Bounded dispatch with preserved semantics

Dispatch per-candidate `route_enrichment` into a bounded executor (cap
~4–8, inside 116's per-host caps), gather with `return_exceptions=True`,
keep the existing per-candidate fallback/metadata logic per result
(success AND failure shapes identical to serial). Result ordering into
`articles` must match serial order (deterministic downstream identity).

**Verify**: `make test-boundaries` passes; a fixture run with one
failing candidate yields the identical item list (order + fallback
shapes) as the serial path — assert it in a test (run both paths in the
test while the serial code still exists, then switch).

### Step 2: Pacing-compliance + thread-safety audit

Prove (test, don't assert): no more than the pacing cap concurrent
requests per host under fan-out (mock-clock or counter test); shared
enricher instances + `enrichment_metrics` recorders are thread-safe for
the paths hit (fix minimally if not — document each fix). Keep the
existing metrics hooks' emitted values identical.

**Verify**: pacing test passes; metrics parity test passes; `make test` passes.

### Step 3: Full gates + perf

Run `make lint && make type && make test && make test-boundaries && make perf`.
Re-run the Step-0 profile; record before/after wall-clock in the commit message.

**Verify**: all green; wall-clock improved (or parity with justification —
e.g. single-candidate sources dominate; still worth it for slow sources).

## Test plan

- Equivalence test: serial vs fanned-out item lists identical (order, fallbacks, metadata).
- Isolation test: one candidate raising → explicit failed item, rest unaffected.
- Pacing test: per-host concurrency never exceeds 116's cap.
- Verification: `make test-boundaries` + `make perf` green.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] Plan 116 DONE (verified at Step 0, recorded in commit message)
- [ ] The `for cand in selected_candidates` serial loop dispatches through the bounded pool
- [ ] Equivalence + isolation + pacing tests exist and pass
- [ ] `make lint && make type && make test && make test-boundaries && make perf` all pass
- [ ] `git diff --name-only 04016ca...HEAD` lists only the in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Plan 116 is not DONE (wait — do not build fan-out without pacing).
- The code at the locations in "Current state" doesn't match the excerpts.
- Equivalence test shows ANY semantic difference (ordering, fallback shape, metrics values).
- Shared enricher state is not thread-safe and the fix exceeds minimal
  locking (report; don't redesign the router).
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

For the human/agent who owns this code after the change lands:

- The pool cap and 116's per-host caps are coupled — changing either
  requires re-running the pacing test.
- If new enrichment strategies are added, they inherit fan-out
  automatically — but their thread-safety must be reviewed (add to the
  strategy checklist).
- **Deferred:** extending fan-out to headless/html collector loops —
  separate plan after this one proves out, unblocked by nothing.
