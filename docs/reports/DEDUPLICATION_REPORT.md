# Deduplication & Hygiene Report (Phase D)

## 1. Duplication Clusters

### Cluster A: The "Three HTTP Clients" Problem

**Pattern**: Multiple inconsistent implementations of HTTP fetching, retries, and safety checks.

- **`async_rss_collector.py`**: Custom `httpx` loop + custom backoff (`_backoff_sleep_async`) + manual redirect handling + inline SSRF check.
- **`html_collector.py`**: `httpx` client + global retry config + `validate_url_safety`.
- **`utils/llm_client.py`**: `requests` (sync) + simple timeout + no backoff.
- **`components/editorial/ai_editor.py`**: `requests` + `tenacity` retry decorator.

**Refactor Target**: `news_collector.infrastructure.http_client`

- Create a single `SmartHttpClient` (wrapper around `httpx`).
- Features: Standardized User-Agent, SSRF validation hook, `tenacity` retry policy, and rate limiting awareness.

### Cluster B: Split Brain LLM Clients

**Pattern**: Two distinct clients interacting with the same Ollama API.

- **`utils/llm_client.py`**: Used by Scorer. Basic sync implementation.
- **`components/editorial/ai_editor.py`**: Used by Refinery. Robust implementation with streaming & cleaning.

**Refactor Target**: `news_collector.infrastructure.llm.OllamaProvider`

- Consolidate into one robust provider.
- Support both Sync (for legacy scorer) and Async (for high-throughput refinery).

### Cluster C: Embedded Parsing Logic

**Pattern**: Collectors are "God Classes" that mix fetching, parsing, cleaning, and filtering.

- **`RSSCollector`**: Contains `_clean_html`, `_extract_authors`, `_extract_summary`.
- **`HtmlCollector`**: Contains `_extract_articles_from_html` (BeautifulSoup logic).

**Refactor Target**: `news_collector.logic.parsers`

- Extract `RssParser` and `HtmlParser` classes.
- Collectors becomes "Coordinators" that strictly handle: Fetch -> Parse -> Normalize -> Save.

## 2. Proposed Module Structure (Minimal)

```text
news_collector/
├── infrastructure/          # [NEW] Low-level I/O mechanics
│   ├── http/
│   │   ├── client.py        # SmartHttpClient (httpx)
│   │   └── security.py      # SSRF & Safety
│   └── llm/
│       └── provider.py      # Unified Ollama Client
├── logic/                   # [NEW] Pure business logic
│   ├── parsers/             # Extracted from collectors
│   │   ├── rss.py
│   │   └── html.py
│   └── cleaning/            # Text, HTML, Author cleaning
└── collectors/              # Orchestrators (Thin)
    ├── rss.py               # Uses http.client + logic.parsers.rss
    └── html.py              # Uses http.client + logic.parsers.html
```

## 3. Top Refactoring Priorities

1.  **Unify HTTP Layer**: Implement `SmartHttpClient` to fix the blocking sleep issues (from Phase B) and SSRF duplication in one go.
2.  **Merge LLM Clients**: Delete `utils/llm_client.py` and move `ai_editor.py` logic to a shared provider.
3.  **Thin Collectors**: Extract parsing logic to allow easier testing of "Rss Parsing" without mocking network calls.
