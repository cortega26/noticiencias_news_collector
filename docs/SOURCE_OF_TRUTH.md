# SOURCE_OF_TRUTH.md

> **"Evidence-first, Spanish-first."**

This document serves as the **Single Source of Truth** for the entire Noticiencias ecosystem. It acts as a central index and high-level definition of the project, linking to detailed documentation where implementation details reside.

---

## 1. Project Identity

*   **Mission**: Democratize access to scientific knowledge for Latin America by prioritizing evidence over clickbait.
*   **Core Value**: Automated curation + Human refinement. We use AI to filter and translate, but humans make the final call.
*   **Primary URL**: `noticiencias.com`

## 2. Ecosystem Overview

The system is a **Hybrid Monorepo** composed of two distinct parts:

| Component | Role | Repository Path | Logic |
| :--- | :--- | :--- | :--- |
| **The Brain** | `news_collector` | `noticiencias_news_collector/` | Python, AI, Scraping, Database, API |
| **The Face** | `noticiencias` | `noticiencias/` | Astro, React, Tailwind, Static Site |

### Data Flow
1.  **Ingestion**: `news_collector` scrapes raw RSS feeds.
2.  **Processing**: Cleaning, deduplication, enrichment (NLP), and scoring.
3.  **Refinery**: Human editors (via Streamlit UI) select and refine articles.
4.  **Publishing**: The Refinery pushes valid Markdown files to the `noticiencias` repo (via PR or direct commit).
5.  **Build**: GitHub Actions builds the Astro site and deploys to GitHub Pages.

---

## 3. Core Technical Truths

### Technology Stack
*   **Backend**: Python 3.13+
*   **Frontend**: Astro 5.0 (Node 18+)
*   **Database**: SQLite (Dev/Default), PostgreSQL (Prod supported)
*   **AI/LLM**: Ollama (Local), supporting Llama 3, Mistral.
*   **Containerization**: Docker & Docker Compose

### Critical Ports
*   **`8501`**: Refinery UI (Streamlit)
*   **`4321`**: Astro Development Server
*   **`11434`**: Ollama API

### Key Locations
*   **Config**: `noticiencias_news_collector/config.toml` (Primary Logic)
*   **Secrets**: `.env` (API Keys, DB Creds)
*   **Logs**: `noticiencias_news_collector/data/logs/`
*   **Raw Data**: `noticiencias_news_collector/data/news.db`

---

## 4. Documentation Index

Do not duplicate information. Go to the source:

| Topic | Primary Document | Location |
| :--- | :--- | :--- |
| **Architecture** | System Design & Diagrams | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| **Operations** | How to run, debug, and fix | [`RUNBOOK.md`](RUNBOOK.md) |
| **AI Agents** | Prompts and editorial logic | [`AGENTS.md`](AGENTS.md) |
| **Frontend** | Astro specific docs | [`../noticiencias/README.md`](../noticiencias/README.md) |
| **Security** | Policy & Vulnerability Mgmt | [`SECURITY.md`](SECURITY.md) |
| **Audit/History** | Migration & Fix logs | [`audit/`](audit/) |

---

## 5. Configuration & Precedence

**Rule of Law:** Environment variables **ALWAYS** override files.

1.  **System Envs**: `NOTICIENCIAS__APP__ENVIRONMENT=production`
2.  **`.env` File**: `NOTICIENCIAS__APP__DEBUG=true`
3.  **`config.toml`**: `[app] debug = false`
4.  **Defaults**: Hardcoded in Python schemas.

*Ref: [`audit/03_config_matrix.md`](audit/03_config_matrix.md)*

---

## 6. Verification & Quality Gates

*   **Linting**: `make lint` (Ruff, Black, Mypy)
*   **Testing**: `make test` (Pytest, Coverage > 80%)
*   **Security**: `make security` (Bandit, Trufflehog, Pip-audit)
*   **CI/CD**: GitHub Actions enforces all the above on every PR.

---
*Created: 2026-01-16. Last Audit: 2026-01-16.*
