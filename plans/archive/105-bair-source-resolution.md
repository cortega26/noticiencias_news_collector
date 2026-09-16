# Plan 105: Resolve the dead `bair_blog` Tier-A source

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat e77a039..HEAD -- news_collector/config/sources.yaml config/ noticiencias/config_schema.py tests/test_feed_reliability.py tests/test_source_reliability.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: ops-config
- **Planned at**: commit `e77a039`, 2026-09-16

## Why this matters

`bair_blog` (Berkeley AI Research — credibility 0.95, tier A, 600s crawl) has
produced zero articles for weeks: every cycle burns ~92s on ConnectTimeouts
against `https://bair.berkeley.edu/blog/feed.xml` (two retries + failure event
+ circuit-breaker trip on 09-04, 09-05, 09-13, 09-14, and the current log),
trips `collector.source.failed` every run, and keeps `database.health.warning
{failed_sources: 2}` plus startup `"2 fuentes fallando"` permanently amber. The
breaker mitigates per-run cost, but a Tier-A slot yielding nothing while
crying warning on every cycle is config debt. After this plan the URL is fixed
(if moved) or the source is honestly disabled/down-weighted with a dated note.

## Current state

The relevant files, each with one line on its role:

- `news_collector/config/sources.yaml` — source catalog, `bair_blog` entry (lines 963-979)
- Log evidence (all read directly from `data/logs/collector.log`): `Retrying _do_execute_request … ConnectTimeout … /blog/feed.xml` → `Circuit breaker tripped: source bair_blog entering COOLDOWN` → `collector.source.failed {source_id: bair_blog, articles_found: 0, latency: ~92.3}`

Excerpt (`news_collector/config/sources.yaml:963-979`):

```yaml
bair_blog:
  name: Berkeley AI Research
  url: https://bair.berkeley.edu/blog/feed.xml
  credibility_score: 0.95
  update_frequency: weekly
  category: artificial_intelligence
  language: en
  impact_factor: null
  description: BAIR Blog
  typical_delay: 0
  content_mode: full_text
  etag: null
  last_modified: null
  _group: INSTITUTIONAL_SOURCES
  tier: "A"
  fetchability_score: 95
  crawl_interval_seconds: 600
```

Repo conventions that apply here:

- Source catalog changes are config, not code — but they affect collection coverage, so verify deliberately and record the decision with a date.
- `make config-validate` is the gate for config changes (`config.toml` path — check whether it covers `sources.yaml`; if not, say so in the report).
- Do NOT invent a new feed URL from memory. BAIR has migrated URLs historically; only a live probe (or an official redirect) justifies a URL change.

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Install   | `make bootstrap`         | declared   | exit 0 |
| Lint      | `make lint`              | declared   | exit 0 |
| ConfigVal | `make config-validate`   | declared   | exit 0 (if it covers sources) |

## Scope

**In scope** (the only files you should modify):

- `news_collector/config/sources.yaml` (`bair_blog` entry only — URL fix, disable flag, or tier/fetchability adjustment per Step 2 verdict)
- `tests/test_feed_reliability.py` / `tests/test_source_reliability.py` — ONLY if they pin `bair_blog`'s URL or enabled state (read first; update expectations only, no new harness)

**Out of scope** (do NOT touch, even though they look related):

- Collector retry/backoff policy, circuit-breaker thresholds, timeouts — all working as designed (that's why this stayed cheap).
- Any other source entry, even if also flaky — report, don't expand.
- The 429 (schneier/biorxiv) and 403 (medicalxpress/techxplore/umich) fetch patterns — external + gracefully degraded, no change warranted.

## Git workflow

- Branch: `advisor/105-bair-source-resolution`
- Conventional commits, e.g. `fix(config): resolve dead bair_blog source`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `Install`, then `Lint` on the unmodified checkout. On any `declared`-command
failure on the clean tree: **STOP and report** with exact output. Confirm the
excerpt above matches `sources.yaml:963-979`.

**Verify**: excerpts match; `make lint` exits 0.

### Step 1: Probe the feed (read-only investigation, no edits yet)

1. `curl -sSI --max-time 25 https://bair.berkeley.edu/blog/feed.xml` — record HTTP code, redirects, TLS outcome, timing. Retry once to rule out a transient blip.
2. If dead/timeout: `curl -sSI --max-time 25 https://bair.berkeley.edu/blog/` (does the blog root resolve? note any redirect target — a redirect to a new domain is evidence, not proof; do NOT adopt an unverified guessed feed path).
3. `git log --oneline -5 -- news_collector/config/sources.yaml` + `git log -S bair --oneline` — when was this entry last touched and has the URL ever been updated?
4. Verdict, one of: (a) feed alive again (transient) → no config change, report and STOP (plan complete with no diff — still report); (b) feed moved (HTTP redirect or official new location verified by fetching it and seeing a valid RSS document) → update `url:`; (c) feed dead with no verified successor → disable the source per its documented mechanism (read how disabled sources are represented — `enabled: false`? removal? follow the file's own convention, check 2-3 disabled entries first) OR down-weight (`fetchability_score`, longer `crawl_interval_seconds`) if the mechanism favors quarantine over removal. Record the choice + date in a YAML comment.

**Verify**: written verdict (a/b/c) with probe transcripts quoted (status lines + final URL only).

### Step 2: Apply the verdict

- (a): no edit. Skip to Step 3 (verification = probe transcripts in the report).
- (b)/(c): edit ONLY the `bair_blog` entry. For (c), prefer the file's own disable convention; add `# 2026-09-16: <verdict + probe summary>` comment.
- If a reliability test pins the old URL/state, update that expectation minimally.

**Verify**: `git diff` shows only the `bair_blog` entry (+ test expectations if any); `make lint` → exit 0; `make config-validate` → exit 0 if applicable (record whether it covers sources.yaml — if not, say so plainly).

### Step 3: Confirm health-signal impact (observational)

The `failed_sources`/`fuentes fallando` warnings clear on the next scheduled collection, which you must NOT trigger wholesale (heavy/network). Instead: run the narrowest source-health check available (check `make healthcheck` semantics first — read the target; if it runs a full collection, do NOT run it; report that clearing is deferred to the next scheduled run). At minimum, prove the config loads and the source resolves as intended (enabled with new URL, or skipped when disabled) via the same loader the collector uses, in a REPL one-liner.

**Verify**: loader-level proof (source enabled/disabled state + effective URL as the collector will see it).

## Test plan

- Config change: loader-level proof + `config-validate` (if applicable) + any reliability-test expectation updates. No new test harness (a live-feed test would be flaky by nature; the existing reliability sweep owns live probing).
- If verdict (a) (transient, no diff): no tests; the probe transcripts are the evidence.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `make lint` (+ `config-validate` if applicable) exit 0
- [ ] Verdict (a/b/c) recorded with probe evidence; config diff (if any) touches only `bair_blog`
- [ ] Loader-level proof of the resulting source state
- [ ] `git diff --name-only e77a039...HEAD` lists only the in-scope files (plus already-merged wave files, expected; verdict (a) may mean zero diff — acceptable, report it)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- No disable convention exists AND removal feels destructive (report options instead of deleting history).
- A guessed successor feed URL can't be verified as a real RSS document (never commit an unverified URL).
- The health check requires a full collection run (report; don't burn one).
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

- If BAIR returns, re-enable by reverting the dated comment block — keep the old URL visible in the comment for that reason.
- The second failing source behind `"2 fuentes fallando"` is out of scope — named in the report if identified during probing, not fixed here.
- Reviewers: the probe transcript is the load-bearing evidence; a config change without it is a guess.
- **Deferred:** source-health-driven auto-quarantine (disable-after-N-failures) — needs a design (flapping guards, re-enable policy); explicitly not this plan.
