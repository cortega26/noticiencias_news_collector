# Plan 141: Validate URL safety before any enrichment fetch strategy runs

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 1ff6926..HEAD -- news_collector/enrichment/ news_collector/infrastructure/requests_client.py news_collector/utils/security.py tests/unit/enrichment/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `1ff6926`, 2026-10-18

## Why this matters

Article URLs come from third-party feed content. The HTTP path enforces a
destination check: `validate_url_safety` (scheme + resolved-IP screening) is
called from `news_collector/infrastructure/requests_client.py:136` on every
request, and the collector's other fetch paths call it too
(`collectors/full_text.py:24`, `collectors/html_collector.py:97`,
`collectors/base_collector.py:589-592`, `logic/workflows/manual_ingest.py:369`,
`serving/api.py:726`). The **enrichment strategy router does not**: the
scrapling and headless browser strategies fetch the raw candidate URL with
third-party fetchers that never touch `SSRFSafeSession`, and no module under
`news_collector/enrichment/` imports the guard at all (verified by grep). Eight
production sources use those strategies (`news_collector/config/sources.yaml`
lines 68, 111, 663, 683, 745, 767, 851, 902), and the collector image enables
the headless path (`Dockerfile:29` — verify). So a malicious or hijacked feed
item can make the production collector issue requests to loopback/internal
services or cloud metadata endpoints, and the browser strategies will happily
open non-http schemes whose rendered body then becomes article content flowing
into enrichment, the LLM chain and publication.

## Current state

- `news_collector/utils/security.py:6` — `validate_url_safety(url)`: raises on
  unsafe schemes/hosts (this is the guard to reuse; read it first and confirm its
  exact contract — it resolves DNS and screens private/link-local ranges).
- `news_collector/enrichment/router.py` — the single dispatch point:
  - `:250` `url = candidate.get("url")` (no validation);
  - `:256+` `if not url: … return {"success": False, "reason": "missing_url", ...}`
    (the local failure shape to reuse);
  - `:340-346` headless branch → `self.headless.enrich(url, source_config)`;
  - `:440-444` `scrapling_http` branch → `self.scrapling_http.enrich(url, source_config)`;
  - `:481-485` `scrapling_stealth` branch → `self.scrapling.enrich(url, source_config)`.
- `news_collector/enrichment/{scrapling_enricher,headless_enricher}.py` — the
  fetchers themselves (`Fetcher.get`, `StealthyFetcher.fetch`, `page.goto`,
  with `bypass_csp=True` in the headless path). They are third-party-driven and
  cannot be relied on to enforce a policy.
- `news_collector/enrichment/http_enricher.py:171` — a comment showing the HTTP
  path expects and handles safety failures as normal input ("URL safety
  validation errors (e.g., relative URLs) are expected inputs").

Repo rules: LAW-B4 (network I/O stays in the edge packages — this stays inside
`enrichment/`), LAW-B7 (explicit structured results, no silent fallbacks).

## Commands you will need

| Purpose          | Command                                                                | Provenance | Expected on success           |
|------------------|------------------------------------------------------------------------|------------|-------------------------------|
| Install/baseline | `make bootstrap`                                                       | declared   | exit 0                        |
| Lint             | `make lint`                                                            | declared   | exit 0                        |
| Types + coverage | `make type`                                                            | declared   | exit 0                        |
| Unit suite       | `make test`                                                            | declared   | all pass                      |
| Boundaries       | `make test-boundaries`                                                 | declared   | exit 0                        |
| Focused tests    | `.venv/bin/pytest tests/unit/enrichment -q --no-cov`                   | declared   | all pass                      |
| Guard absence    | `grep -rn "validate_url_safety" news_collector/enrichment/`             | executed   | **no matches today** (post-change: router.py) |
| Ledger           | `make plans-ledger-check`                                              | declared   | `validate_plans_ledger: OK`   |

Provenance: the `executed` row was run by the advisor (it returned no matches);
the rest are `declared`.

## Scope

**In scope**:

- `news_collector/enrichment/router.py` — the guard call at the dispatch choke point
- `news_collector/enrichment/scrapling_enricher.py` and
  `news_collector/enrichment/headless_enricher.py` — only if you add a
  post-navigation re-check (see Step 2)
- `tests/unit/enrichment/` — new tests (create `__init__.py`-free test modules
  matching the existing directory's style)

**Out of scope** (do NOT touch):

- `news_collector/infrastructure/requests_client.py` and the HTTP enricher — they
  already validate; do not double-validate or refactor them.
- `news_collector/utils/security.py` — reuse as-is. If you believe the guard
  itself is wrong, STOP and report; do not edit it here.
- `sources.yaml` — no source should need to change.
- The deferred `HtmlCollector` SSRF question (a different surface, recorded as
  deferred in the ledger) — do not touch `collectors/`.

## Git workflow

- Branch: `advisor/141-enrichment-url-safety`
- Conventional commit, e.g. `fix(enrichment): validate URL safety before every fetch strategy (plan 141)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `make bootstrap`, `make lint`, `make type`, `make test` on the unmodified
checkout. Red baseline → STOP and report.

**Verify**: every command matches its expected result.

### Step 1: Gate the dispatch point

1. In `router.py`, immediately after the `missing_url` early return, validate
   the URL once:

```python
        try:
            validate_url_safety(url)
        except Exception as exc:  # unsafe destination/scheme, or unresolvable host
            enrichment_metrics.record_failure(source_id or "unknown", "none", "unsafe_url")
            self.logger.warning({...})   # match the neighbours' structured-log style
            return {"success": False, "reason": "unsafe_url", "strategy_used": "none"}
```

   Rules:
   - Import the guard at module level if the file's convention allows (check the
     neighbours), otherwise follow the file's existing local-import pattern.
   - Catch the *specific* exception type the guard raises (read
     `utils/security.py` first). Do not catch bare `Exception` beyond what the
     guard's contract documents.
   - Reuse the existing failure-shape convention (`{"success": False, "reason": ...}`)
     so callers keep working; add `reason="unsafe_url"`.
   - Do not log the URL's resolved IP or any host internals beyond the URL the
     caller already knows.

2. Confirm that this single site covers all four strategies (headless,
   scrapling_http, scrapling_stealth, http) by reading the dispatch flow — if any
   strategy branch is reached before your call, move the call earlier and say so.

**Verify**: `grep -n "validate_url_safety" news_collector/enrichment/router.py` →
one call site; `.venv/bin/pytest tests/unit/enrichment -q --no-cov` → all pass
(existing tests must not need changes; if one does, STOP and report which).

### Step 2: Re-check after browser navigation

3. For the browser-based strategies, the page can redirect. Add a post-navigation
   re-check in `headless_enricher.py` (and the scrapling stealth path if it
   exposes the final URL): after navigation, read the final URL the page landed
   on and validate it with the same guard; on failure, discard the fetched body
   and return the failure shape the module already uses.
   Rule: keep the check cheap (no extra network beyond what the page load
   already did) and never bypass CSP or add flags.

**Verify**: `.venv/bin/pytest tests/unit/enrichment -q --no-cov` → all pass; a
test that a non-http scheme (e.g. `file:`) is rejected in the router.

### Step 3: Prove the production reachability claim

4. Record in the ledger row: the list of sources using scrapling/headless
   strategies (`.venv/bin/python -c "import yaml;d=yaml.safe_load(open('news_collector/config/sources.yaml'));print([k for k,v in d.items() if str(v.get('enrichment_strategy','')).startswith('scrapling')])"`),
   and `grep -n ENABLE_HEADLESS Dockerfile`.

**Verify**: the list and the Dockerfile line are in the ledger row (no secrets involved).

## Test plan

New tests in `tests/unit/enrichment/` (mock only the fetchers/browser — the
guard and the router are the subject):

- **Loopback**: candidate URL `http://127.0.0.1/…` → router returns
  `success: False`, `reason: "unsafe_url"`, and the strategy fetcher is never
  called (assert the mock was not called).
- **Metadata endpoint**: `http://169.254.169.254/latest/meta-data/` → same.
- **Non-http scheme**: `file:///etc/passwd` → same.
- **Private range**: `http://192.168.1.1/` → same.
- **Happy path**: a normal public https URL → existing behaviour unchanged
  (fetcher called once, success shape as before).
- **Each strategy**: parametrise over `enrichment_strategy` ∈ {http,
  scrapling_http, scrapling_stealth, headless} so a future strategy cannot slip
  past the guard.

Model the file after the existing enrichment tests in that directory.

**Verify**: `.venv/bin/pytest tests/unit/enrichment -q --no-cov` → all pass,
including the new cases.

## Done criteria

All must hold:

- [ ] `make lint`, `make type`, `make test`, `make test-boundaries` exit 0
- [ ] `grep -rn "validate_url_safety" news_collector/enrichment/` finds the guard
- [ ] New tests cover loopback / link-local / non-http scheme / private range, per strategy, and fail on the pre-change code (prove once)
- [ ] No change to `sources.yaml`, `requests_client.py`, or `utils/security.py`
- [ ] `git diff --name-only main...HEAD` lists only in-scope files
- [ ] `plans/README.md` row 141 updated; `make plans-ledger-check` → OK

## STOP conditions

- The excerpts do not match the live code (drift) — in particular if the router
  already validates the URL somewhere.
- The guard raises an exception type that would also catch legitimate
  configuration errors (e.g. it rejects scheme-less URLs that sources
  legitimately use) → report the false-positive cases before shipping; do not
  loosen the guard.
- A production source turns out to rely on a non-http scheme → STOP and report
  (that source needs its own decision, not a bypass).
- Existing enrichment tests need modification to pass → report why before editing
  them.

## Maintenance notes

- The router is the choke point on purpose: any future strategy must go through
  it. If someone adds a strategy that fetches before the guard, the parametrised
  test should be extended rather than the guard duplicated.
- Reviewer should scrutinise: no URL or resolved IP is logged in full beyond what
  existing logs already contain; the failure shape matches the module's contract.
- **Deferred:** the `HtmlCollector` follow-on SSRF question (separate surface,
  recorded as deferred in the eighth-pass ledger) and DNS-rebinding TOCTOU
  hardening. Unblocked by a decision, not by this plan.
