# Audit Report: Noticiencias News Collector

## Phase A: Repo Map & Dataflow

### 1. Repository Map & Module Purpose

The repository is structured as a monorepo containing the core news collection backend (`news_collector`) and auxiliary applications (`apps`).

#### Core Modules (`noticiencias_news_collector/news_collector/`)

- **`system.py`**: The Central Nervous System. Orchestrates the entire lifecycle: initialization, collection, validation, and scoring.
- **`collectors/`**: Handles fetching content from external sources (RSS, APIs). Dispatches tasks and normalizes raw inputs.
- **`contracts/`**: Defines Pydantic data models (`CollectorArticleModel`) acting as the interface between collectors and the system. Enforces data integrity at the ingress.
- **`enrichment/`**: NLP stack (spaCy/Pattern) for entity extraction, sentiment analysis, and topic inference.
- **`scoring/`**: Implements the ranking algorithms (recency, credibility, content quality) to prioritize articles.
- **`storage/`**: Database layer (SQLAlchemy + Postgres/SQLite). Defines the canonical `Article` and `Source` models.
- **`editorial/`**: "AI Council" (`EditorialCouncil`) providing automated quality review and feedback using LLMs.
- **`components/editorial/`**: Contains `EditorAgent` (`ai_editor.py`), responsible for the "Refinery" pipeline: translation, adaptation, and drafting.
- **`utils/`**: Shared utilities for text cleaning, deduping (`SimHash`), validation, and logging.
- **`serving/`**: FastAPI implementation to expose collected data.

#### Applications (`noticiencias_news_collector/apps/`)

- **`refinery/`**: A distinct application ("The Refinery") that consumes collected data, performs the "Human-in-the-loop" (or automated) drafting, translation to Spanish, and publishing via Git PRs to the content repository.

#### Entry Points

- **`run_collector.py`**: CLI operator script for running collection cycles, healthchecks, and exports.
- **`main.py`**: Core entry point for the system.
- **`apps/refinery/main.py`**: Orchestrator for the content publishing pipeline.

### 2. Dataflow Pipeline

The data flows separately in two major stages: **Collection** and **Refining**.

#### Stage 1: Collection (Ingest & Score)

1.  **Ingest**: `CollectorDispatcher` triggers specific collectors (e.g., RSS).
2.  **Contract**: Raw data is converted to `CollectorArticleModel` (Pydantic), enforcing basic types and text length.
3.  **Normalization**: Text cleaning and canonical URL generation.
4.  **Enrichment**: `NLPStack` adds entities, simple sentiment, and topics.
5.  **Storage**: Validated articles are saved to the DB (`Article` model) with status `pending`.
6.  **Scoring**: The `Scorer` calculates `final_score` based on source credibility, recency, and impact.
7.  **Filtering**: "AI Council" may provide a second-pass qualitative review.

#### Stage 2: Refining (Translate & Publish)

_Triggered explicitly (e.g., via `apps/refinery/main.py`)_

1.  **Selection**: Articles are fetched from DB (top scored) or via JSON export.
2.  **AI Editor (`EditorAgent`)**:
    - **Translation**: Translates scientific content to Spanish (`_translate_scientific`).
    - **Adaptation**: Rewrites for a LatAm audience (`_adapt_editorial`).
    - **Headlines**: Generates engaging headlines (`_generate_headlines`).
3.  **Drafting**: Generates a Markdown file with Frontmatter (including `refinery_id`).
4.  **Publishing**:
    - Commits to a `target_repo`.
    - Pushes a new branch.
    - Opens a Pull Request (PR) for human review.

### 3. Critical Invariants

The system relies on the following truths to maintain integrity:

1.  **Uniqueness**:
    - `Article.url` must be unique.
    - `Article.content_hash` must be unique (prevents re-ingesting identical content from different URLs).
2.  **Idempotency**:
    - The collection cycle is idempotent; re-running it should not duplicate articles.
    - The Refinery handles filename collisions (`slug` generation) and checks `db_manager.is_processed` to avoid re-publishing.
3.  **State Flow**:
    - Articles move `pending` -> `processed` (after PR creation).
4.  **Language**:
    - **Ingest**: Primarily English (or source language).
    - **Refinery Output**: Always Spanish (target audience).

### 4. External Dependencies

- **Data Sources**: RSS Feeds, APIs.
- **LLM Provider**: Ollama (for translation/editorial).
- **Git/GitHub**: For sourcing legacy data and publishing new content.
- **Database**: SQLite (dev) / Postgres (prod).
