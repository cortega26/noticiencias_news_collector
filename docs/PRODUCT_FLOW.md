# Product Flow

Status: Active  
Authority: Subordinate to `docs/SOURCE_OF_TRUTH.md` and `docs/AGENTS.md`

This document traces the full life cycle of a published Noticiencias article — from RSS
discovery to a live page on the front end — as it works **today**.  It is a reading guide
for the combined system, not a target-state manifesto.

For per-stage operational details, see:

- Back-end architecture and package map → [`docs/ARCHITECTURE.md`](ARCHITECTURE.md)
- Cross-repo contract definitions → [`docs/PIPELINE_CONTRACTS.md`](PIPELINE_CONTRACTS.md)
- CI gate reference → [`docs/ci.md`](ci.md)
- Daily dev bootstrap → [`docs/RUNBOOK_LOCAL_DEV.md`](RUNBOOK_LOCAL_DEV.md)

---

## Stage Map

```
RSS feeds
   │
   ▼
[1. Collection]         news_collector/collectors/
   │                    news_collector/infrastructure/
   │
   ▼
[2. Storage]            news_collector/storage/database.py
   │                    SQLite (dev) / PostgreSQL (prod)
   │
   ▼
[3. Enrichment]         news_collector/enrichment/
   │                    news_collector/scoring/
   │                    news_collector/validation/
   │                    news_collector/taxonomy/
   │                    news_collector/editorial/
   │
   ▼
[4. Export]             ExportContractV2 (news_collector/contracts/export.py)
   │                    → data/export/ artifact
   │
   ▼
[5. Refinery editorial] apps/refinery/  (Streamlit UI)
   │                    Human review, approve/reject
   │
   ▼
[6. Publication]        news_collector/logic/workflows/refinery_engine.py
   │                    news_collector/components/publishing/
   │                    → MDX file conforming to AstroPost schema
   │
   ▼
[7. GitHub PR]          cortega26/noticiencias  src/content/posts/<slug>.md
   │                    Automated PR opened by the back-end
   │
   ▼
[8. Front-end CI]       cortega26/noticiencias  GitHub Actions
   │                    npm run lint && npm run validate:content && npm run build
   │
   ▼
[9. Deploy]             GitHub Pages  (cortega26/noticiencias)
                        Live article at noticiencias.cl/post/<permalink>
```

---

## Stage Detail

### Stage 1 — Collection

**Entrypoint:** `scripts/run_collector.py` (use this; see `docs/RUNBOOK_LOCAL_DEV.md`)

The collector fetches configured RSS/Atom feeds, extracts article metadata and body text,
deduplicates by canonical URL, and writes raw articles into the database.

Key packages: `news_collector/collectors/`, `news_collector/infrastructure/`,
`news_collector/logic/parsers/`.

### Stage 2 — Storage

All articles transit through SQLite (development) or PostgreSQL (production).  The ORM
models live in `news_collector/storage/models.py`.  Migration baseline is managed by
Alembic (`alembic/`).

### Stage 3 — Enrichment

Each collected article passes through the enrichment pipeline:

| Module | Responsibility |
| --- | --- |
| `news_collector/enrichment/` | Translation, summarisation, excerpt generation |
| `news_collector/scoring/` | Editorial relevance and quality scoring |
| `news_collector/validation/` | Schema and quality gate enforcement |
| `news_collector/taxonomy/` | Category and tag normalisation |
| `news_collector/editorial/` | Review-status assignment |
| `news_collector/reranker/` | Final ranking before export |

### Stage 4 — Export

Enriched articles are serialised as `ExportContractV2` (see `news_collector/contracts/export.py`)
and written to a local export artifact.  The Refinery UI reads this artifact.

`schema_version: 1` export artifacts are still tolerated with logged warnings for legacy
compatibility.

### Stage 5 — Refinery Editorial Review

The Streamlit application at `apps/refinery/` loads the export artifact and presents each
candidate article to a human editor.  The editor approves or rejects articles and optionally
adjusts titles, categories, or tags.

**Run locally:** `make refinery`

Approved articles move to Stage 6.

### Stage 6 — Publication

`news_collector/logic/workflows/refinery_engine.py` and `news_collector/components/publishing/`
convert an approved `ExportContractV2` article into a Markdown/MDX document whose frontmatter
conforms to `AstroPost` (see `news_collector/contracts/frontend_schema.py`).

**Cross-repo contract:**

| Back-end source | Front-end authority |
| --- | --- |
| `news_collector/contracts/frontend_schema.py` (`AstroPost`) | `../noticiencias/src/content.config.ts` (Zod schema) |

Field-level parity is enforced by `tests/test_contracts_sync.py::test_frontend_schema_field_parity`
on every CI run.  If these two files diverge, that test fails.

Publication rules enforced at this stage:

- `image_alt` (or `image.alt`) must be present.
- `categories` must contain exactly one primary editorial category; `Editorial` is reserved
  for first-party Noticiencias content.
- `permalink` must not collide with any existing post.
- `date` must be intentional (not a default).

### Stage 7 — GitHub PR

The publication component opens an automated pull request against `cortega26/noticiencias`,
adding the new MDX file under `src/content/posts/`.

Configuration: `config.toml` `[github]` section  
PR author: the GitHub token in the deployment environment's `GITHUB_TOKEN` secret.

### Stage 8 — Front-end CI

On PR creation the front-end CI runs:

```bash
npm run lint
npm run validate:content   # Zod schema validation across all posts
npm run build              # Full Astro build — fails fast on schema or route errors
npm run test:dist
npm run test:audit
```

If any gate fails, the PR is blocked and the article is **not** published.  The back-end is
not automatically notified; the operator must inspect the PR.

### Stage 9 — Deploy

On PR merge the front-end CI builds and deploys to GitHub Pages.  The article is live at
`https://noticiencias.cl/post/<permalink>`.

---

## Cross-Repo Failure Modes

| Symptom | Most likely cause | Where to look |
| --- | --- | --- |
| PR opened but `validate:content` CI fails | `AstroPost` / `config.ts` field mismatch | `tests/test_contracts_sync.py`, `news_collector/contracts/frontend_schema.py`, `src/content.config.ts` |
| PR opened but `npm run build` fails | Missing required frontmatter field in published MDX | Stage 6 publication logic; check `image_alt`, `categories`, `date` |
| Articles collected but never reach Refinery | Export artifact missing or empty | Stage 4: check `data/export/`; run `python scripts/run_collector.py --dry-run` |
| Refinery blank screen | Export schema mismatch (V1 vs V2) | `apps/refinery/main.py` compatibility layer; check collector output `schema_version` |
| Article approved but PR not opened | GitHub token missing or invalid | `config.toml` `[github]` section; environment `GITHUB_TOKEN` |

---

## Invariants

These must hold at all times.  If a change would break one, escalate before merging.

1. Every MDX file committed to `src/content/posts/` must satisfy the Zod schema in
   `src/content.config.ts`.
2. `news_collector/contracts/frontend_schema.py` field names must be a superset of the
   top-level Zod field names in `src/content.config.ts`.  The parity test enforces this.
3. The back-end **never** directly pushes to the front-end `main` branch.  All changes go
   through a PR so the front-end CI gates run.
4. `Editorial` category is reserved.  The publication layer must refuse to assign it to
   translated third-party articles.

---

## Related Documents

| Document | What it adds |
| --- | --- |
| [`docs/PIPELINE_CONTRACTS.md`](PIPELINE_CONTRACTS.md) | Contract shapes, V1/V2 compatibility, and current failure semantics |
| [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) | Full package map and dependency direction |
| [`docs/RUNBOOK_LOCAL_DEV.md`](RUNBOOK_LOCAL_DEV.md) | Local setup and per-stage run commands |
| [`docs/runbook.md`](runbook.md) | Operational alert runbook (production incidents) |
| [`docs/ci.md`](ci.md) | All CI jobs, gates, and timeout configuration |
| `../noticiencias/AGENTS.md` | Front-end architecture laws and review governance |
