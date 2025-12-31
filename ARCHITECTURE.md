# Noticiencias System Architecture & Runbook

This document describes the architecture, components, and operational workflows of the **Noticiencias News Collector & Refinery**, now consolidated into a **Hybrid Monorepo**.

## 🏗️ High-Level Architecture

The system is designed as a **Hybrid Monorepo** containing two primary subsystems that share a common core:

1.  **News Collector (`news_collector/`):** A headless Python package responsible for scraping, processing, and scoring scientific news from various RSS feeds.
2.  **Refinery (`apps/refinery/`):** A Streamlit-based "Human-in-the-loop" Admin Panel for reviewing, refining (via AI), and publishing articles to the static site.

These components share:
-   **Data Models & Database:** Single source of truth for article data.
-   **Configuration:** Unified `config.toml` and `.env` management.
-   **Dependencies:** Managed via a single `setup.py` / `pyproject.toml`.

```mermaid
graph TD
    subgraph "External"
        RSS[RSS Feeds]
        Ollama[Ollama AI]
        GitHub[Target Repo (Jekyll)]
    end

    subgraph "Hybrid Monorepo"
        subgraph "Core Package (news_collector)"
            Collector[RSS Collector]
            Pipeline[Processing Pipeline]
            DB[(Database)]
        end

        subgraph "Applications (apps/)"
            Refinery[Refinery UI (Streamlit)]
        end
    end

    RSS --> Collector
    Collector --> Pipeline
    Pipeline --> DB
    DB <--> Refinery
    Refinery <--> Ollama
    Refinery -->|PRs| GitHub
```

---

## 📂 Directory Structure

```text
noticiencias_news_collector/
├── news_collector/          # 📦 CORE PACKAGE (The "Brain")
│   ├── collectors/          # Fetching logic (RSS, Robots.txt)
│   ├── config/              # Configuration schemas & loaders
│   ├── enrichment/          # NLP, Keyword extraction, Language detection
│   ├── storage/             # Database models (SQLAlchemy)
│   └── utils/               # Shared utilities
│
├── apps/                    # 🚀 APPLICATIONS
│   └── refinery/            # The Admin Panel (Streamlit)
│       ├── admin_panel.py   # Entry point for UI
│       └── main.py          # Orchestrator logic
│
├── data/                    # Local data storage (SQLite, exports)
├── tests/                   # Unit and End-to-End tests
├── config.toml              # Main configuration file
├── .env                     # Secrets (API Keys)
├── pyproject.toml           # Project metadata & tool config
├── setup.py                 # Package installation script
├── run_collector.py         # CLI Entry point for Collector
└── docker-compose.yml       # Container orchestration
```

---

## ⚙️ Core Components

### 1. News Collector System
**Goal:** Ingest raw content and turn it into structured, scored candidates.
*   **Ingestion:** Fetches RSS feeds, respecting `robots.txt` and rate limits.
*   **Enrichment:** Detects language, extracts entities (spacy/nltk), and keywords.
*   **Scoring:** Assigns a score (0.0 - 1.0) based on source credibility, freshness, and keyword matches.
*   **Storage:** Saves to SQLite (default) or Postgres.

### 2. Refinery (Admin Panel)
**Goal:** Empower a human editor to review top candidates and publish them.
*   **Interface:** Built with Streamlit.
*   **AI Integration:** Connects to **Ollama** (Llama 3, Mistral) to translate and rewrite articles per specific editorial guidelines ("punchy," "accessible").
*   **GitOps:** Automates the Git workflow: clones the target Jekyll repo, creates a branch, commits the markdown file, and pushes a PR.

---

## 📘 Runbook: How to Operate

### 1. Installation & Setup
The project is installed as an **editable package**, meaning changes to `news_collector/` are immediately reflected in `apps/refinery/`.

```bash
# 1. Install dependencies and the package in editable mode
pip install -e .

# 2. Check installation
python -c "import news_collector; print(news_collector.__file__)"
```

### 2. Running the Collector
The collector runs as a CLI script. It can be scheduled via cron or run manually.

```bash
# Run a full collection cycle
python run_collector.py

# Run in simulation mode (no DB writes)
python run_collector.py --dry-run

# Run for specific sources
python run_collector.py --sources nature science_daily
```

**Output:** Articles are saved to the `news.db` (SQLite) by default.

### 3. Running the Refinery
The Refinery is a web interface for interacting with the data.

```bash
# Launch the Streamlit app
streamlit run apps/refinery/admin_panel.py
```
*   Access at: `http://localhost:8501`
*   **Tab 1 (AI & Refinery):** Configure Ollama config and target repos.
*   **Tab 2 (Scraper & Scoring):** Adjust scoring weights and keywords.
*   **Tab 3 (Operations):** Select cached articles, review them, and click "Refine & Publish".

### 4. Docker Deployment
You can run the entire stack (Collector + Refinery + DB) using Docker.

```bash
docker-compose up --build
```

---

## 🔧 Configuration

### `config.toml`
Controls the logic of the collector.
*   **Collection:** Interval, max articles.
*   **Scoring:** Weights for credibility, recency, etc.
*   **Sources:** List of RSS feeds (e.g., Nature, ScienceDaily).

### `.env`
Controls secrets and infrastructure paths.
```ini
# Core
LOG_LEVEL=INFO
DATABASE_URL=sqlite:///news.db

# Refinery
GITHUB_TOKEN=ghp_xxxx
OLLAMA_API_URL=http://localhost:11434/api/generate
SOURCE_REPO_URL=https://github.com/cortega26/noticiencias_news_collector
TARGET_REPO_URL=https://github.com/cortega26/noticiencias
```

---

## 🛠️ Troubleshooting

**Issue: "Module not found: news_collector"**
*   **Fix:** Ensure you installed the package with `pip install -e .` in the root directory.

**Issue: "Streamlit cannot find config"**
*   **Fix:** The Refinery expects `config.toml` in the root. If running from a clear environment, ensure `NEWS_COLLECTOR_PATH` in `.env` points to the repo root.

**Issue: "Ollama Connection Error"**
*   **Fix:** Ensure Ollama is running (`ollama serve`) and the URL in `.env` or the UI settings is correct.

