# Plan 141: Validate URL safety before any enrichment fetch strategy runs

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 7754536c..HEAD -- news_collector/enrichment/ news_collector/infrastructure/requests_client.py news_collector/utils/security.py tests/unit/enrichment/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `7754536c`, 2026-10-19 (refreshed after a correct first-execution STOP — see below)

### Refresh note (2026-10-19)

The first execution attempt implemented Step 1 and STOPped exactly as the plan's
STOP condition asked: adding the guard breaks 16 of the 67 existing tests in
`tests/unit/enrichment/test_router.py`, because they build candidates with the
literal URL `http://x` and the guard fails closed on an unresolvable host
(`socket.getaddrinfo("x")` → `gaierror` → `ValueError`). That is a *fixture*
consequence, not a behaviour problem — the guard is doing its job — and the tests
need the network boundary stubbed (AGENTS §4.1 allows mocks at boundaries; DNS is
one). The first executor verified the remedy: one class-level
`@patch("news_collector.enrichment.router.validate_url_safety", MagicMock())` on
`TestEnrichmentStrategyRouter`, beside its existing three class-level patches,
returns the directory to 67 passed. It did not apply it (it was told to stop) and
it also flagged a second-order effect: those 51 currently-passing tests only pass
because real DNS resolves `example.com`, so the guard would give the unit suite a
live-network dependency. Both points are now in scope below; nothing else changed.

### Refresh note 2 (2026-10-19) — scope extension after a second correct STOP

The second attempt implemented the whole plan (guard at the router + post-navigation
re-checks, 21 new tests, hermetic `tests/unit/enrichment/` under `unshare -rn` = 88
passed) and then STOPped because two declared gates went red on fixtures in files
the plan had not scoped. That is the same class as refresh 1, so the scope now
covers fixture-level stubbing **across `tests/`** (assertions stay frozen):

1. `tests/unit/test_headless_enricher_simple.py::test_enrich_flow` — a bare
   `MagicMock` page makes `page.url` a mock, so the new final-URL re-check fails
   closed. Verified remedy: set `mock_page.url = "http://example.com"`.
2. `tests/unit/collectors/test_rss_enrichment_fanout.py::test_pacing_per_host_cap_never_exceeded_under_fanout`
   — candidates use `https://paced.example.com` (RFC 2606 reserved, never
   resolves), so the guard rejects before `HostPacer`. Verified remedy: patch
   `news_collector.enrichment.router.validate_url_safety` in the test's existing
   patch block.
3. `tests/integration/test_headless_activation.py` — fixtures use `http://test.com`
   (does not resolve here); 2 of 3 tests fail after the change. Verified remedy:
   one class-level guard patch.

Also folded in from that attempt: `scrapling_http` follows redirects, so it needs
the same final-URL re-check as the browser strategies (see Step 2 item 4) — its
initial URL was guarded but its redirect targets were not, and `openai_blog` uses
that strategy.

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
- `tests/unit/enrichment/test_router.py` — **fixture-level stubbing only**: add
  the class-level guard patch (and stub `socket.getaddrinfo` where a test relies
  on real DNS). Do not change any assertion, expected value, or test name there.
- `tests/unit/enrichment/test_host_pacer.py`,
  `tests/unit/test_headless_enricher_simple.py`,
  `tests/unit/collectors/test_rss_enrichment_fanout.py`,
  `tests/integration/test_headless_activation.py` — **fixture-level stubbing
  only** (a class-level guard patch, or setting a mock's `url` attribute). Refresh
  note 2 records the verified remedy for each. No assertion, expected value, or
  test name may change.
- **Rule for any other test file the guard breaks:** fixture-level stubbing is in
  scope wherever the file lives; changing an expectation is not.

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

3. Stub the boundary in the existing test class (the remedy the first attempt
   verified): add `@patch("news_collector.enrichment.router.validate_url_safety", MagicMock())`
   to `TestEnrichmentStrategyRouter` in `tests/unit/enrichment/test_router.py`,
   beside its existing three class-level patches, injecting the parameter into
   the methods that need it — or patch `socket.getaddrinfo` where a test depends
   on real DNS. Fixture-level stubbing only: no assertion, expected value, or test
   name in that file may change, and no test may be deleted or renamed.

**Verify**: `grep -n "validate_url_safety" news_collector/enrichment/router.py` →
one call site; `.venv/bin/pytest tests/unit/enrichment -q --no-cov` → all pass;
`grep -n "validate_url_safety\|getaddrinfo" tests/unit/enrichment/*.py` → the
stub is visible.

### Step 2: Re-check after browser navigation

3. For the browser-based strategies, the page can redirect. Add a post-navigation
   re-check in `headless_enricher.py` (and the scrapling stealth path if it
   exposes the final URL): after navigation, read the final URL the page landed
   on and validate it with the same guard; on failure, discard the fetched body
   and return the failure shape the module already uses.
   Rule: keep the check cheap (no extra network beyond what the page load
   already did) and never bypass CSP or add flags.

4. `scrapling_http` follows redirects (`Fetcher.get(..., follow_redirects=True)`),
   so the **final** URL must be re-checked exactly like the browser strategies:
   after the fetch, validate the response's final URL with the same guard; on
   failure discard the body and return the module's failure shape. If the library
   does not expose the final URL on the response object, STOP and report the
   residual (it is a real hole: `openai_blog` uses this strategy) rather than
   leaving it open silently.

**Verify**: `.venv/bin/pytest tests/unit/enrichment -q --no-cov` → all pass; a
test that a non-http scheme (e.g. `file:`) is rejected in the router; and the
directory is **hermetic** — prove it by running it with DNS unavailable
(`unshare -rn .venv/bin/pytest tests/unit/enrichment -q --no-cov` on Linux, or
document why that is unavailable and show the stubs instead). No test in that
directory may resolve a real hostname.

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
- **Happy path**: a normal public https URL with `socket.getaddrinfo` patched
  (precedent: `tests/unit/utils/test_security.py`) → existing behaviour
  unchanged (fetcher called once, success shape as before). The happy path must
  not depend on real DNS, and neither may the router tests it sits beside.
- **Each strategy**: parametrise over `enrichment_strategy` ∈ {http,
  scrapling_http, scrapling_stealth, headless} so a future strategy cannot slip
  past the guard.

Model the file after the existing enrichment tests in that directory.

**Verify**: `.venv/bin/pytest tests/unit/enrichment -q --no-cov` → all pass,
including the new cases.

## Done criteria

All must hold:

- [ ] `make lint`, `make type`, `make test`, `make test-boundaries` exit 0
- [ ] `make test-integration` exits 0 (the guard touches integration fixtures too)
- [ ] `grep -rn "validate_url_safety" news_collector/enrichment/` finds the guard
- [ ] New tests cover loopback / link-local / non-http scheme / private range, per strategy, and fail on the pre-change code (prove once)
- [ ] `tests/unit/enrichment/` is hermetic (no live DNS): the stub is visible in the diff and the offline run is recorded
- [ ] No assertion, expected value, or test name changed in `tests/unit/enrichment/test_router.py` (diff shows fixture stubbing only)
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
- You need to change an *assertion*, an expected value, or a test name in any
  test (or delete one) to make the guard pass → STOP and report; fixture-level
  stubbing — anywhere in `tests/` — is in scope, rewriting expectations is not.

## Maintenance notes

- The router is the choke point on purpose: any future strategy must go through
  it. If someone adds a strategy that fetches before the guard, the parametrised
  test should be extended rather than the guard duplicated.
- Reviewer should scrutinise: no URL or resolved IP is logged in full beyond what
  existing logs already contain; the failure shape matches the module's contract.
- **Deferred:** the `HtmlCollector` follow-on SSRF question (separate surface,
  recorded as deferred in the eighth-pass ledger) and DNS-rebinding TOCTOU
  hardening. Unblocked by a decision, not by this plan.
