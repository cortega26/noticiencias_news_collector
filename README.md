# Noticiencias News Collector

![Python Version](https://img.shields.io/badge/python-3.13+-blue.svg)

Scientific news aggregation pipeline and editorial tooling for the Noticiencias project. Requires Python 3.13+.

## Overview

This repository contains the backend ingestion pipeline plus the Streamlit-based Refinery UI used to review, refine, and publish articles to the Astro site.

## Features

- **RSS Feed Ingestion**: Collects news from configured RSS sources.
- **Content Enrichment**: Cleans and normalizes article text.
- **Scoring & Reranking**: Scores articles based on relevance and quality.
- **Storage**: Persists data to SQLite/Postgres (schema validation included).
- **Monitoring**: Logs and tracks collection health.
- **Refinery UI**: Human-in-the-loop editorial panel for review and publishing.
- **Per-Phase AI Config**: Independently configure models for Translation, Editing, and Headlines.

## Installation

### Prerequisites

- Python 3.13+
- pip (or `make bootstrap` to provision a local venv)

### Setup

1.  Clone the repository:

    ```bash
    git clone https://github.com/cortega26/noticiencias_news_collector.git
    cd noticiencias_news_collector
    ```

2.  Install dependencies:
    ```bash
    make bootstrap
    ```
    This creates `.venv/` and installs pinned dependencies from `requirements.lock`.

## Usage

### Running the Collector

To run the main collection pipeline:

```bash
python run_collector.py
```

Common flags:

```bash
python run_collector.py --dry-run
python run_collector.py --sources nature science_daily
```

### Running the Refinery (Streamlit)

```bash
streamlit run apps/refinery/admin_panel.py
```

Access at `http://localhost:8501`.

### Running Ollama (LLM)

The Refinery uses Ollama for local LLM inference.

1. Install Ollama from `https://ollama.com/`.
2. Start the Ollama server:
   ```bash
   ollama serve
   ```
3. Pull a model (example):
   ```bash
   ollama pull llama3
   ```
4. Set environment variables in `.env`:
   - `OLLAMA_API_URL=http://localhost:11434/api/generate`
   - `OLLAMA_MODEL=llama3`

### Configuration

Configuration is managed via `config.toml` (root) and `.env`.

#### Per-Phase Model Configuration (Recommended for CPU)

For standard CPU deployments, use **Llama 3.2** for all phases to ensure reasonable performance (< 5 mins/article). 14B+ models require a GPU or very long processing times.

```toml
[ollama]
# Base Model (Fallback)
model = "llama3.2:latest"

# Per-Phase Overrides (Optional)
translator_model = "llama3.2:latest"
editor_model = "llama3.2:latest"
headlines_model = "llama3.2:latest"
```

### Testing

Run the test suite using `pytest`:

```bash
make test
```

### Docker

Run the full stack (Collector + Refinery + DB) with Docker:

```bash
docker-compose up --build
```

## Docs

- **Architecture**: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- **Agents Protocol**: [`docs/AGENTS.md`](docs/AGENTS.md)
- **Source of Truth**: [`docs/SOURCE_OF_TRUTH.md`](docs/SOURCE_OF_TRUTH.md)
- **Operations Runbook**: [`docs/ops/RUNBOOK.md`](docs/ops/RUNBOOK.md)
- **Configuration Schema**: [`docs/config_fields.md`](docs/config_fields.md)

## Quality Gate (Editorial Regression Protection)

To prevent silent degradations in editorial quality, we maintain a set of "Golden Cases" that define structural and semantic invariants.

### Usage

When modifying prompts, models, or pipeline logic, verify that the golden set still passes:

```bash
make quality-gate
```

This runs the current pipeline against cached scenarios in `quality_gate/golden/` and verifies strict constraints (forbidden phrases, mandatory sections, length bounds).

To visually inspect changes, use snapshot mode:

```bash
python scripts/quality_gate.py --snapshot
```

This saves generated outputs to `quality_gate/snapshots/` for manual review.

## Development & Quality

We maintain high code quality standards using a unified suite of tools.

- **Check Quality**: `make quality` (Runs Ruff, Mypy, Bandit, pip-audit, and Semgrep)
- **Auto-Fix**: `make quality-fix` (Automatically fixes format and simple lint errors)
- **Standards Guide**: See [`QUALITY.md`](docs/dev/QUALITY.md) for details on the tools and how to handle failures.

## Security

This project uses `gitleaks` to prevent secret leakage.
Please check `.gitleaks.toml` for configuration.

## License

Copyright (c) 2026 Noticiencias Team. All Rights Reserved.
