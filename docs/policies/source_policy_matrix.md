# Source & Model Policy Matrix

This document tracks legal/robot-policy requirements for every configured data source and the main ML/NLP libraries used by the News Collector System.

## Data Sources

| Source ID | Domain | Terms / Policy | robots.txt highlights | Notes |
| --- | --- | --- | --- | --- |
| nature | nature.com | Springer Nature Terms of Use (authentication required) | `Disallow: /search`, `Disallow: */1000$`, `Disallow: /*proof=*`【eefec7†L1-L20】 | Terms page redirects through Nature's identity provider; keep cached copy for compliance reviews. |
| science | science.org | [Science Terms of Service](https://www.science.org/content/page/science-terms-service) | `Disallow: /action`, `Disallow: /help`, `Allow: /action/showFeed`【2296ad†L1-L20】 | Feed endpoints explicitly allowed; respect other restricted paths. |
| cell | cell.com | [Elsevier Website Terms & Conditions](https://www.elsevier.com/legal/elsevier-website-terms-and-conditions) | robots.txt returns HTTP 403 (access controlled)【2759f5†L1-L8】 | Requires authenticated UA; treat as “allow by contract only” and follow Elsevier’s automated access rules. |
| nejm | nejm.org | [NEJM Terms of Use](https://www.nejm.org/page/terms-of-use) | `Disallow: /action`, `Disallow: /search`, `Allow: /action/showJournal`【0abb34†L1-L20】 | Only fetch documented feeds; block generic scraping of gated areas. |
| scientific_american | scientificamerican.com | [Scientific American Terms of Use](https://www.scientificamerican.com/page/terms-of-use/) | `Crawl-Delay: 5`, `Disallow: /checkout`, blocks `GPTBot`, `ChatGPT-User`, etc.【6a559b†L1-L20】 | Respect 5s delay per domain and avoid blocked AI user agents. |
| new_scientist | newscientist.com | [New Scientist Terms & Conditions](https://www.newscientist.com/terms/) | Blocks numerous AI/automated bots; `Disallow: /feed/`, `/login/`, `/search/` for `User-agent: *`【596698†L1-L20】【2aefc6†L1-L24】 | Use custom UA not in prohibited list and avoid disallowed endpoints. |
| ars_technica | arstechnica.com | [Ars Technica Terms of Service](https://arstechnica.com/terms-of-service/) | Disallows many crawler UAs; global rules block `/search`, `/comments`, `/wp-content/`【00f8d4†L1-L20】【b5ec30†L1-L24】 | Fetch RSS feeds only; keep crawl footprint minimal. |
| phys_org | phys.org | [Phys.org Terms](https://phys.org/terms/) | HTTPS robots requests return `400 Bad Request` HTML【ab8d5e†L1-L20】 | Requires standard browser UA; verify updated robots policy before new integrations. |
| mit_news | news.mit.edu | [MIT News Terms of Use](https://news.mit.edu/terms-of-use) | Drupal robots allow static assets, disallow `/admin/`, `/search/`, auth endpoints【afd001†L1-L20】【363d44†L1-L24】 | Combine robots restrictions with MIT News content reuse policy. |
| stanford_news | news.stanford.edu | [Stanford News Terms of Use](https://news.stanford.edu/terms-of-use) | `Crawl-delay: 10`, disallow admin/design paths and `/search`【68a454†L1-L20】 | Enforce ≥10s delay per Stanford host. |
| nasa_news | nasa.gov | [NASA Use Policy](https://www.nasa.gov/about/highlights/HP_Privacy.html) | `User-agent: *` followed by `Allow: /` (full access)【637aa6†L1-L6】 | Still honour NASA media guidelines when republishing. |
| nih_news | nih.gov | [NIH Web Policies & Notices](https://www.nih.gov/about-nih/website-policies) | Drupal robots allowing assets, disallowing `/admin/`, `/search/`, auth endpoints【4b45dd†L1-L20】 | NIH content is public domain but attribution is required. |
| biorxiv | biorxiv.org | [bioRxiv Terms & Conditions](https://www.biorxiv.org/terms) | robots.txt served via Cloudflare challenge (HTTP 403)【16f1c9†L1-L28】 | Use official APIs/OAI feeds; coordinate with Cold Spring Harbor policy team. |
| arxiv_ai | export.arxiv.org | [arXiv Terms of Use](https://info.arxiv.org/help/terms/index.html) | `User-agent: *` with `Disallow: /` (no generic crawling)【6d7c80†L1-L1】 | Only access published RSS/API endpoints covered by arXiv’s automated access guidelines. |

## ML / Analytics Libraries

| Component | Purpose in pipeline | License (per package metadata) | Notes |
| --- | --- | --- | --- |
| nltk | Language detection & tokenization | Apache License 2.0【0f4cc0†L8-L9】 | Provides word tokenization and corpora loaders. |
| textblob | Sentiment & simple NLP | Metadata missing explicit license【0f4cc0†L9-L11】 | Treat as MIT per upstream docs; verify before redistribution. |
| scikit-learn | Feature engineering / scoring models | BSD-3-Clause【0f4cc0†L11-L13】 | Ensure attribution in downstream products. |
| numpy | Numerical primitives | BSD-3-Clause (with bundled third-party notices)【0f4cc0†L13-L81】 | Include vendor notices when redistributing binaries. |
| httpx | Optional async HTTP client | BSD-3-Clause【0f4cc0†L113-L113】 | Required for Async collector. |
| sqlalchemy | ORM / DB abstraction | MIT【0f4cc0†L113-L114】 | Compatible with commercial deployments. |
| loguru | Structured logging | Upstream metadata missing license (MIT per project docs)【0f4cc0†L114-L115】 | Confirm before bundling with proprietary agents. |
| opentelemetry-api / sdk | Telemetry export | Apache-2.0【0f4cc0†L115-L117】 | Keep NOTICE files when packaging agents. |
| prometheus-client | Metrics exporter | Apache-2.0 & BSD-2-Clause mix【0f4cc0†L117-L117】 | Include combined license texts in docker images. |

## Operational Checklist

- Maintain a vault-backed `DATABASE_URL`; never commit credentials.
- Enforce robots.txt delays per source (e.g., 10s for Stanford, 5s for Scientific American).
- Track domains with blocked/unknown robots (cell.com, phys.org, biorxiv.org) and secure written permission before scaling ingestion.
- Re-run this audit whenever sources or libraries change.
