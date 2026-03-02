# SOURCE_OF_TRUTH.md

Version: 2.0 (Institutional Alignment Edition) Status: Active & Binding
Created: 2026-01-16 Last Updated: 2026-03-02

---

> **"Evidence-first, Spanish-first. Deterministic by design."**

This document serves as the **Single Source of Truth** for the entire
Noticiencias ecosystem.\
It defines mission, system boundaries, architectural principles, and
governance hierarchy.

If any document conflicts with this one, this document prevails.

---

# 1. Project Identity

## Mission

Democratize access to scientific knowledge for Latin America by
prioritizing evidence over clickbait.

## Core Value

Automated curation + Human refinement.\
AI filters, scores, and structures --- humans make final editorial
decisions.

## Primary URL

`noticiencias.com`

---

# 2. Foundational Architectural Principles

The Noticiencias ecosystem is governed by the following principles:

### 2.1 Evidence-First Systems

- Editorial decisions prioritize verifiable scientific evidence.
- Automated processes must be auditable.
- No opaque scoring logic without traceability.

### 2.2 Deterministic Identity

- Canonical identity of published articles is immutable.
- Reprocessing must be idempotent.
- Canonical URLs and slugs are deterministic and persistent.
- No time-based or random mutation in identity paths.

### 2.3 Contract-Enforced Boundaries

- All cross-subsystem communication must be explicitly defined.
- Schema drift must be isolated through adapters.
- Implicit structural assumptions are prohibited.

### 2.4 Tests as Architectural Proof

- Tests encode invariants.
- Critical system behaviors must be covered.
- Regression without explicit approval is forbidden.

These principles are enforced operationally in: - `AGENTS.md` (Backend
Law) - `ARCHITECTURE.md` (System Design) - CI/CD Quality Gates

---

# 3. Ecosystem Overview

The system is a **Hybrid Monorepo** composed of two distinct but
coordinated components:

---

Component Role Repository Path Logic

---

**The Brain** `news_collector` `noticiencias_news_collector/` Python, AI,
Scraping,
Database,
API

**The Face** `noticiencias` `noticiencias/` Astro,
React,
Tailwind,
Static Site

---

---

## 3.1 High-Level Data Flow

1.  **Ingestion**
    - `news_collector` scrapes raw RSS feeds.
2.  **Processing**
    - Cleaning
    - Deduplication
    - Enrichment (NLP)
    - Scoring
    - Validation (contract-bound)
3.  **Refinery**
    - Human editors (Streamlit UI) select and refine articles.
    - Canonical identity is locked at publication.
4.  **Publishing**
    - Refinery pushes valid Markdown files to the `noticiencias` repo.
    - Push via PR or controlled commit.
5.  **Build & Deploy**
    - GitHub Actions builds Astro site.
    - Deploys to GitHub Pages.

---

## 3.2 Determinism Guarantee

The following are immutable once published:

- Filename
- Publication date
- Canonical URL
- Slug
- Refinery ID

Reprocessing the same article must produce identical canonical
artifacts.

Non-determinism is allowed only in: - Logging - Telemetry - Runtime
metrics

Never in canonical identity path.

---

# 4. Core Technical Truths

## Technology Stack

### Backend

- Python 3.13+
- Pydantic Contracts
- SQLite (Dev/Default)
- PostgreSQL (Prod Supported)

### Frontend

- Astro 5.0+
- Node 18+
- React
- Tailwind

### AI / LLM

- Ollama (Local)
- Llama 3
- Mistral

### Containerization

- Docker
- Docker Compose

---

# 5. Critical Ports

Port Purpose

---

8501 Refinery UI (Streamlit)
4321 Astro Dev Server
11434 Ollama API

---

# 6. Key Locations

Purpose Location

---

Config `noticiencias_news_collector/config.toml`
Secrets `.env`
Logs `noticiencias_news_collector/data/logs/`
Raw Data `noticiencias_news_collector/data/news.db`

---

# 7. Documentation Hierarchy

Hierarchy of authority:

1.  SOURCE_OF_TRUTH.md
2.  AGENTS.md (Backend Law)
3.  ARCHITECTURE.md
4.  RUNBOOK.md
5.  Inline code documentation

Do not duplicate information across documents.

Primary references:

Topic Document

---

Architecture `ARCHITECTURE.md`
Backend Law `AGENTS.md`
Operations `RUNBOOK.md`
Frontend `../noticiencias/README.md`
Security `SECURITY.md`
Audit `audit/`

---

# 8. Configuration & Precedence

**Rule of Law:** Environment variables ALWAYS override files.

Order of precedence:

1.  System Environment Variables\
    `NOTICIENCIAS__APP__ENVIRONMENT=production`

2.  `.env` File\
    `NOTICIENCIAS__APP__DEBUG=true`

3.  `config.toml`\
    `[app] debug = false`

4.  Hardcoded Defaults\
    Defined in Python schemas

Reference: `audit/03_config_matrix.md`

---

# 9. Verification & Quality Gates

All Pull Requests must satisfy:

## 9.1 Linting

`make lint` - Ruff - Black - Mypy

## 9.2 Testing

`make test` - Pytest - Structural coverage enforcement -
Invariant-protecting paths must not regress

Numeric coverage target (\>80%) is secondary to invariant protection.

## 9.3 Security

`make security` - Bandit - Trufflehog - Pip-audit

## 9.4 CI/CD Enforcement

GitHub Actions enforces all gates on every PR.

No merge allowed if: - Critical invariant violated - Deterministic
identity compromised - Contract boundary broken - Tests removed without
approval

---

# 10. Governance & Evolution

This document may evolve under controlled amendment:

1.  Rationale documented
2.  Impact analysis provided
3.  Invariant impact assessed
4.  Human approval granted
5.  Version incremented
6.  Changelog updated

Architecture is durable but adaptable.

---

End of SOURCE_OF_TRUTH.md --- Version 2.0 Institutional Alignment
Edition
