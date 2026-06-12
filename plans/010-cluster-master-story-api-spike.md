# Plan 010: Spike — expose article clusters as a "master story with sources" surface

> **Executor instructions**: This is a **design/spike plan**, not a build-everything
> plan. Your deliverable is an investigation writeup + a thin, well-tested
> read-only slice — NOT a full feature. Do not change the clustering algorithm or
> the publication pipeline. Honor STOP conditions. Update this plan's row in
> `plans/README.md` when done.
>
> **Drift check (run first)**:
> `git diff --stat b30248f..HEAD -- news_collector/storage/article_repository.py news_collector/serving/api.py news_collector/contracts/`
> Re-confirm the anchors below before designing.

## Status

- **Priority**: P3
- **Effort**: M (spike-scoped)
- **Risk**: LOW (additive, read-only)
- **Depends on**: none (but coordinate with 005 since both touch `serving/api.py`)
- **Category**: direction
- **Planned at**: commit `b30248f`, 2026-06-12

## Why this matters

The pipeline already **clusters near-duplicate articles** (a breaking story appearing across many sources) but only ever exposes individual articles. Readers can see three variations of the same finding, diluting the feed and hiding the product's real signal ("N independent sources reported this"). The capability is built and unused — surfacing it is high-leverage. This spike answers *whether and how* to expose clusters, and lands a minimal read-only slice to prove it, before anyone commits to the full feature (export contract, frontend rendering, refinery UI).

## Grounding evidence (the capability already exists)

- `news_collector/storage/models.py:203` — `Article.cluster_id: Mapped[str | None]` column already persisted.
- `news_collector/storage/models.py:236` — `Index("idx_articles_cluster_recency", "cluster_id", "collected_date")` already exists (so cluster-keyed queries are cheap).
- `news_collector/storage/article_repository.py` — `_assign_cluster(...)` (around line 923) and `_revalidate_cluster(...)` populate/merge clusters via simhash on save; `news_collector/utils/dedupe.py` computes the clustering confidence.
- `news_collector/serving/api.py` — the read layer exposes `GET /v1/articles` only; **no cluster grouping** and no `related` concept.
- `news_collector/contracts/export.py` and `contracts/frontend_schema.py` (`AstroPost`, fields at lines 57–104) — **no `cluster_id` / `related_articles`** field anywhere.

So: data model ✅, index ✅, population ✅; **exposure ❌**.

## Spike deliverables (what "done" means)

1. **An investigation note** at `docs/spikes/cluster-master-story.md` answering the open questions below.
2. **A thin, tested, read-only API slice**: one endpoint that, given an article id, returns the other articles sharing its `cluster_id` (the "sources of this story"). No contract/export/frontend changes, no pipeline changes.
3. A short **recommendation**: is the full feature worth building, and what is the smallest contract change that would carry it to the frontend?

## Open questions the note must answer (investigate in the repo)

- **Canonical member**: when N articles share a cluster, which is the "master"? (highest `final_score`? earliest `collected_date`? Check whether anything already designates one — search for cluster-canonical logic in `article_repository.py` and `reranker/`.)
- **Cluster stability**: `_revalidate_cluster` merges clusters on new saves — can a `cluster_id` change after publication? If so, a public "related" view must tolerate re-clustering. Document the observed behavior (read the merge logic; don't guess).
- **Cardinality**: typical and max cluster size in the current DB (run a read-only query: group `articles` by `cluster_id`, count). This sizes the response and pagination needs.
- **Contract shape**: the smallest addition to `AstroPost`/export that would let the frontend render "also reported by: …" — propose `cluster_id: Optional[str]` + `related: List[{title, source, url}]`, but only as a *proposal* in the note, not an implementation.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Serving tests | `.venv/bin/pytest tests/test_serving_api.py -q` | all pass (incl. your new test) |
| Lint / type | `make lint && make type` | exit 0 |
| Cluster size query (read-only) | a small `.venv/bin/python` snippet using the repo's session | prints distribution |

## Scope

**In scope:**
- `docs/spikes/cluster-master-story.md` (create) — the investigation note + recommendation
- `news_collector/serving/api.py` — add ONE read-only endpoint (e.g. `GET /v1/articles/{id}/related`)
- `tests/test_serving_api.py` — test for the new endpoint

**Out of scope (do NOT touch in this spike):**
- `contracts/export.py`, `contracts/frontend_schema.py` — propose changes in the note only; do not implement.
- The clustering algorithm (`_assign_cluster`, `_revalidate_cluster`, `utils/dedupe.py`).
- The publication pipeline / refinery / the sibling frontend repo.
- Any write endpoint.

## Git workflow

- Branch: `advisor/010-cluster-spike`
- Commits: one for the note, one for the endpoint+test.
- Do NOT push or open a PR.

## Steps

### Step 1: Investigate and write the note

Answer every "Open question" above by reading the cited code and running read-only DB queries. Record findings (with `file:line` references) in `docs/spikes/cluster-master-story.md`. End with a one-paragraph recommendation (build / don't build / build a smaller version) and the proposed contract delta.

### Step 2: Implement the thin read-only endpoint

Add `GET /v1/articles/{id}/related` to `serving/api.py`, modeled on the existing `list_ranked_articles` handler (same `Depends(get_db)` session pattern, same response-model discipline — define a small Pydantic response model alongside the existing ones). Behavior: look up the article's `cluster_id`; if null, return an empty list; else return the other articles in that cluster (id, title, source, url, score), ordered deterministically (e.g. by `final_score` desc then id). Use the existing `idx_articles_cluster_recency` — query by `cluster_id`.

Keep it read-only and bounded (cap the number returned, e.g. 20).

**Verify:** `.venv/bin/pytest tests/test_serving_api.py -q` → all pass.

### Step 3: Test the endpoint

In `tests/test_serving_api.py`, add tests (model after the existing serving tests' fixture/client setup):
- article with no cluster → `200`, empty list.
- article in a cluster of 3 → returns the 2 siblings (not itself), deterministically ordered.
- unknown id → `404` (or the repo's existing not-found convention — match it).

**Verify:** `make test` includes the new tests and stays green.

## Done criteria

ALL must hold:

- [ ] `docs/spikes/cluster-master-story.md` exists and answers all four open questions with `file:line` evidence + a recommendation
- [ ] `GET /v1/articles/{id}/related` exists, is read-only, bounded, and deterministically ordered
- [ ] New serving tests cover no-cluster / clustered / not-found and pass
- [ ] `make type` exits 0; `make lint` exits 0; `make test` exits 0
- [ ] No changes to contracts, clustering, or the pipeline (`git status` shows only in-scope files)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report (with your findings so far) if:

- The investigation shows `cluster_id` is unstable enough post-publication that a public "related" view would be misleading — report this; it changes whether the full feature is worth building.
- Cluster sizes are pathological (e.g. thousands of articles share one id due to a clustering bug) — that's a separate bug to surface, not something to paper over in an endpoint.
- The endpoint cannot be added without changing the export contract or pipeline — re-scope and report; do not exceed the spike boundary.

## Maintenance notes

- This deliberately stops short of the frontend. If the recommendation is "build it," the follow-up is: add the proposed fields to `AstroPost`/export (with the cross-repo contract sync test `tests/test_contracts_sync.py` in mind — the frontend Zod schema in `../noticiencias/src/content/config.ts` must move in lockstep), then render in the frontend.
- A reviewer should confirm the new endpoint is read-only, paginated/bounded, and does not regress the existing `/v1/articles` query (especially if plan 005's index work landed in the same file).
