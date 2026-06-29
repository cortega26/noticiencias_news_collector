# Noticiencias News Collector

*Parte del [ecosistema Tooltician](https://tooltician.com) — periodismo científico, reproducible y open-source.*

![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)
[![Tooltician](https://tooltician.com/badge.svg)](https://tooltician.com)

Backend ingestion, editorial automation, and publication orchestration repo for the Noticiencias product.

This repository is the system of record for collection, enrichment, scoring, storage, Refinery workflows, and the contract mirror used to publish into the sibling frontend repo `../noticiencias`. It is not the frontend site repo and it is not a monorepo; the product spans two coordinated repositories with explicit boundaries.

## Current Responsibilities

- collect and normalize source articles
- score, validate, rerank, and persist them
- expose read-oriented API endpoints
- run the Streamlit Refinery UI
- generate publication artifacts and open pull requests against the frontend repo
- maintain the mirrored frontend publication contract in `news_collector/contracts/frontend_schema.py`

## Current Shape

- `news_collector/contracts/`: sealed cross-boundary models and adapters
- `news_collector/system/`: orchestration, bootstrap, reporting, observability wiring
- `news_collector/collectors/`, `enrichment/`, `infrastructure/`: ingestion and external I/O
- `news_collector/storage/`: database engines, ORM models, persistence
- `news_collector/scoring/`, `validation/`, `taxonomy/`, `editorial/`, `reranker/`: policy and decision logic
- `news_collector/logic/workflows/`: workflow composition, publication, manual ingest, image briefs
- `news_collector/components/editorial/` and `components/publishing/`: editorial and publishing collaborators
- `news_collector/serving/`: FastAPI read surface
- `apps/refinery/`: Streamlit Refinery application

## Preferred Entry Points

```bash
make bootstrap
python scripts/run_collector.py --dry-run
make refinery
make lint
make type
make test
```

More local commands:

- `make quality`
- `make quality-ci`
- `make e2e`
- `make perf`
- `make config-validate`
- `make config-docs-check`
- `make build`

Notes:

- `scripts/run_collector.py` is the preferred collector CLI entrypoint used by CI and automation.
- **`main.py` has been removed.** Previously it was a deprecated compatibility wrapper; `scripts/run_collector.py` is the only collector entrypoint.

## Cross-Repo Contract

Publication into the frontend repo depends on two files staying aligned:

- backend mirror: `news_collector/contracts/frontend_schema.py`
- frontend render contract: `../noticiencias/src/content/config.ts`

If either changes, treat it as a cross-repo contract change.

## Governance Docs

- [`docs/INDEX.md`](docs/INDEX.md): full docs directory index — start here if you are looking for any document.
- [`docs/SOURCE_OF_TRUTH.md`](docs/SOURCE_OF_TRUTH.md): documentation hierarchy, repo boundary, and non-negotiable current truths.
- [`docs/AGENTS.md`](docs/AGENTS.md): binding review and change law for this repo.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): actual package responsibilities and dependency direction.
- [`docs/PIPELINE_CONTRACTS.md`](docs/PIPELINE_CONTRACTS.md): contract-bearing flows and current failure semantics.
- [`docs/PRODUCT_FLOW.md`](docs/PRODUCT_FLOW.md): end-to-end product flow from RSS article to live published page.
- [`docs/RUNBOOK_LOCAL_DEV.md`](docs/RUNBOOK_LOCAL_DEV.md): first-time setup and daily development runbook for the full system.
- [`docs/ci.md`](docs/ci.md): workflow and gate reference.
- [`docs/runbook.md`](docs/runbook.md): current operational alert runbook.
- [`docs/audits/2026-04-source-of-truth-audit.md`](docs/audits/2026-04-source-of-truth-audit.md): documentation audit for this pass.
- [`docs/dev/source-of-truth-backlog.md`](docs/dev/source-of-truth-backlog.md): prioritized follow-up backlog.

## Historical Material

- `audit/`, `docs/audits/`, and archived planning docs are useful evidence and history, but they are not architectural authority unless explicitly referenced by the active docs above.

---

*Part of the [Tooltician](https://tooltician.com) ecosystem — periodismo científico, reproducible y open-source.*
