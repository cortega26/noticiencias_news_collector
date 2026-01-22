# Noticiencias News Collector

![Python Version](https://img.shields.io/badge/python-3.13+-blue.svg)

Scientific news aggregation pipeline for the Noticiencias project. Requires Python 3.13 o superior.

## Overview

This repository contains the news collector service, responsible for fetching, cleaning, scoring, and storing scientific news articles from various RSS feeds and sources.

## Features

- **RSS Feed Ingestion**: Collects news from configured RSS sources.
- **Content Enrichment**: Cleans and normalizes article text.
- **Scoring & Reranking**: Scores articles based on relevance and quality.
- **Storage**: Persists data to a local database/file system (schema validation included).
- **Monitoring**: Logs and tracks collection health.

## Installation

### Prerequisites

- Python 3.13+
- pip

### Setup

1.  Clone the repository:

    ```bash
    git clone <repository_url>
    cd noticiencias_news_collector
    ```

2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
    _Alternatively, using a virtual environment:_
    ```bash
    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    ```

## Usage

### Running the Collector

To run the main collection pipeline:

```bash
python main.py
```

### Configuration

Configuration is managed via `config/config.toml` (or environment variables). Key settings include:

- RSS Feed URLs
- Scoring thresholds
- Output paths

### Testing

Run the test suite using `pytest`:

```bash
pytest
```

## Security

This project uses `gitleaks` to prevent secret leakage.
Please check `.gitleaks.toml` for configuration.

## License

Copyright (c) 2026 Noticiencias Team. All Rights Reserved.
