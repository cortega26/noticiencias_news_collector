# Plan 117: Hosted fetch fallback evaluation (standby)

> **Executor instructions**: This is a standby evaluation. Do NOT execute it
> while no source defeats the local ladder — the entry gate below is binding.
> When the gate fires, follow the steps and run every verification command.
> Update the status cell for plan 117 in `plans/README.md` when done — unless a
> reviewer dispatched you and told you they maintain the index.
>
> **Drift check (run first when triggered)**:
> `git diff --stat 40934de..HEAD -- news_collector/enrichment/router.py news_collector/config/sources.py news_collector/config/sources.yaml plans/README.md plans/117/baseline-measurements.md`
> On mismatch vs the excerpts below, refresh them before measuring.

## Status

- **Priority**: P2
- **Effort**: M (when triggered; S to re-verify baseline)
- **Risk**: LOW (read-only evaluation; provider keys are owner-gated)
- **Depends on**: plan 116 (per-host pacing) and the 2026-09-29 discovery_only remediation
- **Category**: reliability / direction
- **Planned at**: collector commit `40934de`, 2026-09-29

## Why this matters

Some publishers block automated article fetches even when our feed collection
works. The 2026-09-29 remediation removed five summary-only sources from the
fetch path (`discovery_only`), and plan 116 addresses the remaining burst
offenders. If a source ever defeats the full local ladder — plain HTTP,
`scrapling_http` (curl_cffi TLS), `scrapling_stealth`/headless, proxies, pacing
— a hosted fetch/unblocker API is the next step, but it carries recurring cost,
third-party data exposure, and ToS implications. This plan pre-builds that
decision (candidate matrix, cost caps, exact integration contract) so it can be
executed in days, without integrating anything speculatively.

## First measurements (2026-09-29)

Full table in `baseline-measurements.md`. Summary:

- 7 previously-failing URLs, single polite requests with the collector UA:
  5×200 (`schneier`, `biorxiv`, `restofworld`, `medicalxpress`, `techxplore`),
  `news.umich.edu` 403, `caltech.edu` apex TLS-000.
- Control arm: the **existing** `scrapling_http` (`Fetcher`, curl_cffi) fetched
  the umich URL 200 (62 KB). The 403 is TLS fingerprinting, not IP.
- `caltech.edu` `www` host serves 200; the source is `discovery_only` already.
- Verdict: **no current source defeats the local ladder** → provider evaluation
  stays standby.

## Entry gate (all must hold before executing Step 2+)

1. A specific source systematically blocks after all of: plain HTTP,
   `scrapling_http`, `scrapling_stealth`/headless (with `ENABLE_HEADLESS` and a
   justified budget), proxy escalation, and plan 116 pacing.
2. The source is editorially important enough to justify third-party cost,
   data-handling review, and ToS acceptance.
3. The owner approves an evaluation key with a hard daily credit cap.

## Candidate matrix (verify prices/terms at execution time — they change)

| Provider | Surface for us | Auth | Pricing signal (2026-09-29) | Stealth | Output |
|---|---|---|---|---|---|
| TinyFish | Fetch API (`api.fetch.tinyfish.ai`) | `X-API-Key` | Fetch free at time of check; Agent/Browser metered | full browser render + rotating proxies/stealth included | markdown / JSON / HTML |
| Firecrawl | `/scrape` | API key | metered credits | render + proxy tiers | markdown / JSON |
| ZenRows | universal scraper API | API key | metered | anti-bot + proxy | HTML / JSON |
| ScrapingBee | scraping API | API key | metered | JS render + proxy | HTML |
| Browserbase (+Stagehand) | rented browser session | API key | metered session minutes | stealth browser | custom extraction |

Evaluation criteria (all measured, not quoted): success rate on the frozen URL
set, latency p50/p95, cost per 1 000 articles, data-retention/ToS terms, HTTP/SDK
simplicity, failure semantics (what a failed fetch costs), key scoping.

## Integration contract (design only — a build plan is required before code)

- New strategy `hosted_fetch` added to the `config/sources.py` whitelist and the
  router dispatch, exactly like `discovery_only` (early, explicit branch).
- Per-source opt-in plus `strategy_justification`; never the default; the
  `http`/`scrapling_*`/`headless` paths are untouched.
- Secret only via env var (e.g. `HOSTED_FETCH_API_KEY`); provider endpoint
  configurable; nothing in `config.toml` or `sources.yaml`.
- Hard cost caps: max calls/day and estimated spend logging; refusal is a
  normal failure that falls back like any other strategy.
- Output contract identical to `HttpEnricher` (`content`, `raw_content`,
  `strategy_used`) so validation/editorial rules need no change.
- Tests: router dispatch, client with mocked HTTP (success/429/timeout/cap),
  no real network; fixtures for the frozen URL set.
- Privacy/security: send only public article URLs; document what the provider
  receives and retains; run `make quality` for the new dependency.

## Steps (execute only when the entry gate fires)

0. Drift check + green baseline; re-run `baseline-measurements.md` to confirm
   the local ladder still fails on the target source.
1. Freeze the URL set (10-20 article URLs from the blocked source) and write a
   scratch measurement script under `/tmp` (never committed).
2. Owner supplies evaluation keys with hard caps; record spend.
3. Run the matrix: each provider × URL, N=2 minimum; record success, latency,
   bytes, cost, failure mode. Re-run the local control arm in the same session.
4. Results table + recommendation in this spec (one provider, the local ladder,
   or "do not fetch this source").
5. Contract delta: any refinement to the integration contract above + a build
   plan sketch (separate plan number) with tests and cost guardrails.
6. Close: update the ledger row, record keys revoked/rotated as needed.

## Test plan

- Measurement harness is scratch; no repo tests are added by this plan.
- If Step 5 yields a build plan, its tests are defined there.

## Done criteria

- [ ] Entry gate recorded verbatim before any measurement
- [ ] Frozen URL set + per-provider results table with cost and latency
- [ ] Local control arm re-measured in the same session
- [ ] Recommendation recorded (including "keep the local ladder" as a valid outcome)
- [ ] Integration contract refined or confirmed; build plan number named if needed
- [ ] plans/README.md row updated; no keys or values committed anywhere

## STOP conditions

- Entry gate not met → STOP; do not spend credits or add dependencies.
- A provider requires committing a key or a config value → STOP (env only).
- Measurements show the source needs authentication/paywall access, not just
  anti-bot bypass → STOP; that is a licensing decision, not a fetch technique.
- ToS/robots review is unclear for a target publisher → STOP and take it to a
  source-policy decision (summary-only/retire) instead.

## Maintenance notes

- Re-verify provider pricing, free tiers, and data terms every time this plan
  is considered; the 2026-09-29 signals are not commitments.
- Prefer a Fetch-style API over Agent/Browser surfaces: we need clean article
  text, not multi-step interaction; per-step billing scales badly.
- Plan 116 should reduce the burst offenders to zero; if it does, the provider
  question only matters for genuinely hard single-request blockers.
