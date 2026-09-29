# Plan 116: Per-host pacing for article enrichment

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. This repo enforces its plans ledger in CI
> (`make plans-ledger-check` → `scripts/validate_plans_ledger.py`). When done,
> update the status cell for plan 116 in `plans/README.md` — unless a reviewer
> dispatched you and told you they maintain the index.
>
> **Drift check (run first)**: `git diff --stat 0688100..HEAD -- news_collector/enrichment/router.py news_collector/infrastructure/requests_client.py news_collector/config/sources.yaml plans/README.md`
> On mismatch vs the "Current state" excerpts, compare live content; level of
> drift decides whether to STOP or refresh the excerpts. If the router no longer
> routes per-candidate through `route_enrichment`, STOP.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED (touches the enrichment hot path; changes fetch timing, not content rules)
- **Depends on**: none (the discovery_only source fix in the 2026-09-29 fetch-warning remediation removed five offenders; this plan covers the rest)
- **Category**: reliability / source politeness
- **Planned at**: collector commit `0688100`, 2026-09-29

## Why this matters

The 2026-09-29 log triage across the stored run archives found burst-driven
article-page failures that are not source defects: single live probes to the
same URLs return 200, while the collector sees 403/429 because it fires many
concurrent per-article requests at one publisher. Top offenders after the
discovery_only remediation: `schneier_security` (29×429), `biorxiv` (19×429),
`rest_of_world` (7×429), plus periodic bursts on other full-text sources.
`HttpEnricher` warns once per blocking host, and
`requests_client` retries 429 with tenacity, but nothing bounds the request
rate per host. Per-host pacing turns those bursts into polite sequential
traffic, reducing blocked fetches and source-side hostility without touching
editorial policy.

## Current state

- `news_collector/enrichment/router.py`: `route_enrichment` is called once per
  selected candidate from `rss_collector.py`'s deep-processing loop. It routes
  to `http`, `scholarly`, `headless_fallback`, `scrapling_stealth` or
  `discovery_only`; there is
  no per-host interval or concurrency control. Five summary-only sources now
  use `enrichment_strategy: discovery_only` (2026-09-29 remediation), which
  removes their article fetches; the remaining full-text sources still burst.
- `news_collector/infrastructure/requests_client.py`: `RobustRequestsClient`
  sets browser-like headers, fails fast on 403/404, and retries transient
  errors, but has no shared per-host throttle across instances.
- Evidence (counts from `data/logs/*.log.gz` + `data/logs/collector.log`,
  2026-09-29 triage): `HttpEnricher fetch failed` 429/403 groups listed above;
  `Retrying _do_execute_request ... 429` for schneier (64×), biorxiv (41×),
  restofworld (16×). Live single requests returned 200 for all probed offenders.
- Enrichment metrics exist (`enrichment_metrics.record_attempt/success/failure/
  cost`) and can anchor the before/after measurement.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Targeted tests | `.venv/bin/python -m pytest tests/unit/enrichment tests/unit/infrastructure -q` | all pass |
| Lint | `make lint` | exit 0 |
| Boundaries | `make test-boundaries` | exit 0 |
| Full baseline | `make test` | exit 0 |
| Plans ledger | `python3 scripts/validate_plans_ledger.py` | `validate_plans_ledger: OK` |
| Full gate | `make verify-ci` | exit 0 |

## Scope

**In scope**: `news_collector/enrichment/router.py` (or a small pacing helper
under `news_collector/enrichment/`), `news_collector/infrastructure/
requests_client.py` or a new narrow throttle module, config schema/docs for any
new `[enrichment]` knobs, and targeted tests.

**Out of scope**: changing any source's `enrichment_strategy`/`content_mode`/
`fetch_mode` values; proxy-pool behavior; adding paid scraping services;
changing editorial gates; LLM-based fetch workarounds.

## Steps

### Step 0: Baseline + drift check

Run the drift command above; record HEAD. Run targeted tests + `make lint` on
the unmodified tree; a broken baseline means STOP.

### Step 1: Measure

Quantify per-host article-fetch volume for one fresh run (or the last log):
requests per host, 403/429 counts, and wall time. Record the numbers in this
spec (implementation record) — they are the before picture.

### Step 2: Design + implement the throttle

Minimum design: a per-host minimum interval (e.g. 1-2 s) and a small per-host
concurrency cap applied wherever article pages are fetched through the router/
enricher, shared across collector threads, with a bounded wait (no deadlock,
timeout-safe). Prefer a narrow helper (`news_collector/enrichment/host_pacer.py`
or similar) injected where `HttpEnricher`/router are constructed, over hidden
module globals. Config knobs in `[enrichment]` (`host_min_interval_seconds`,
`host_max_concurrency`) with schema + docs updates; defaults must preserve
current behavior for unconfigured hosts is NOT required — choose defaults that
are polite but do not obviously slow the pipeline (justify in the record).

### Step 3: Tests

Fake clock/sleep seam (the tenacity `nap.sleep` seam is the house pattern).
Cover: second request to the same host waits the configured interval; different
hosts do not block each other; concurrency cap respected; failure/timeout
releases the slot; disabled knobs preserve current behavior.

### Step 4: Re-measure + gates

Run the same measurement as Step 1 on a post-change run; record 403/429 counts
and wall time. Then run the full gate.

### Step 5: Close

Append the implementation record (design, before/after numbers, gate outputs)
and update the plans ledger row.

## Test plan

- Unit tests for the pacer/limiter and router integration (same-host wait,
  cross-host independence, concurrency cap, release-on-failure).
- Measurement before/after on real runs (same host set), documented in-spec.

## Done criteria

- [ ] Drift check + baseline recorded
- [ ] Per-host pacing implemented with config knobs + docs
- [ ] Unit tests cover same-host wait, cross-host independence, cap, release-on-failure
- [ ] Before/after measurement recorded (403/429 per host, wall time)
- [ ] `make lint`, `make test-boundaries`, `make test` exit 0
- [ ] plans/README.md row updated

## STOP conditions

- Drift makes the router flow unrecognizable (STOP and refresh the plan).
- The design requires changing editorial output or source strategy values
  (out of scope — STOP).
- Pacing cannot be implemented without a global lock that serializes all hosts
  (STOP and re-scope).
- Measurement shows the burst is not temporal (e.g. persistent 403 on single
  requests too) — that is a source-policy decision, not pacing.

## Maintenance notes

- Keep the throttle seam injectable; tests must never sleep for real.
- Re-check the offenders after two weeks; if a host still blocks single polite
  requests, take it to a source-policy review (summary_only/retire/replace).
- `the_verge` HTML responses were transient on live probe; not this plan.
