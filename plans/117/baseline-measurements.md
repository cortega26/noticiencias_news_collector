# Plan 117 baseline measurements — blocked-source URL set

Date: 2026-09-29 (19:20–19:25 UTC) · Method: single polite GET per URL with the
collector's real UA (`Chrome/120 + NoticienciasBot/1.0`), 2 s apart; control arm
via the project venv (`scrapling 0.4.15`, `curl_cffi 0.16.3`).

## Plain client (RobustRequestsClient UA equivalent)

| URL (from the 2026-09-29 triage) | HTTP | time | bytes |
|---|---|---|---|
| `schneier.com/.../python-now-has-a-post-quantum-encryption-library.html` | 200 | 0.51s | 67,421 |
| `biorxiv.org/content/10.64898/2026.08.04.737285v1?rss=1` | 200 | 0.59s | 125,464 |
| `restofworld.org/2026/china-ai-boyfriend-ban-bytedance-doubao/` | 200 | 0.17s | 70,765 |
| `medicalxpress.com/news/2026-08-melanoma-drug-based-herpes-virus.html` | 200 | 1.07s | 191,424 |
| `techxplore.com/news/2026-08-electronic-skin-enables-tunable-proximity.html` | 200 | 1.06s | 164,836 |
| `news.umich.edu/cyclospora-questions-confusion-return-as-michigan-reports-2-deaths-...` | **403** | 0.36s | 6,186 |
| `caltech.edu/about/news/new-info-from-ancient-rocks-upends-popular-theory` | **000** (TLS) | 0.39s | 0 |

## Control arm — existing local ladder

- `scrapling.fetchers.Fetcher` (the library behind the `scrapling_http`
  strategy) on the umich URL: **200, 62,738 bytes** — the 403 is TLS
  fingerprinting, not IP reputation.
- Same arm on caltech apex: TLS error `unable to get local issuer certificate
  (60)`; on the `www.caltech.edu` variant of the same article: **200, 212,291
  bytes** (Cloudflare-served). The apex failure is a hostname/cert problem, not
  a block.
- `StealthyFetcher` (the `scrapling_stealth` strategy) was not exercised; it
  requires `ENABLE_HEADLESS=true` plus browser deps. Not needed by this sample.

## Verdict

- 5/7 URLs fetch fine with the plain client; they only failed in the archived
  logs under burst conditions → plan 116 pacing, not a provider problem.
- `news.umich.edu` (persistent 403) is cleared by the **already-installed**
  `scrapling_http` strategy.
- `caltech.edu` is already `discovery_only` (no article fetch); its feed is the
  `www` host, which serves fine. A future full-text need would be a URL-rewrite
  question, not a provider question.
- Therefore: **no hosted provider is needed today.** Plan 117 stays standby
  with the candidate matrix and integration contract pre-built.
