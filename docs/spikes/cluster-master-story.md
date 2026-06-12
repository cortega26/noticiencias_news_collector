# Spike: master story with sources

## Scope

This spike evaluates the existing duplicate clusters as a read-only "also reported by" surface. It does not change clustering, publication, export contracts, or frontend rendering.

## Findings

### Canonical member

No stored field or existing selection rule designates a canonical cluster member. Cluster assignment chooses the nearest simhash candidate, breaking ties by publication-time distance and article id (`news_collector/storage/article_repository.py:1027-1038`), but that choice only determines cluster membership. The reranker independently orders articles by score, publication date, and source (`news_collector/reranker/reranker.py:24-31`) and does not inspect `cluster_id`.

A future master-story surface should choose the highest `final_score`, then newest `collected_date`, then highest id for deterministic ties. That is a presentation rule, not persisted cluster identity. The thin API slice therefore exposes siblings only and does not claim that any member is canonical.

### Cluster stability

Cluster membership is mutable. When a new article matches members from multiple clusters, `_assign_cluster` rewrites every member of the other clusters to the selected target id (`news_collector/storage/article_repository.py:1049-1058`). After a single save, `_revalidate_cluster` may also move an article whose simhash is too distant from the selected anchor into a newly generated cluster (`news_collector/storage/article_repository.py:1062-1103`). Bulk saves perform assignment and cluster merging but do not call the same revalidation path (`news_collector/storage/article_repository.py:503-608`).

Consequently, `cluster_id` must not become a permanent public URL or publication identity. A related-articles response is acceptable as an eventually consistent, request-time view: clients should render the returned sources without caching cluster membership indefinitely.

### Cardinality

The configured SQLite database was queried read-only on June 12, 2026. It contained 864 articles, all with a non-null `cluster_id`, distributed across 841 clusters:

| Cluster size | Number of clusters |
| ---: | ---: |
| 1 | 831 |
| 2 | 8 |
| 4 | 1 |
| 13 | 1 |

The observed maximum is 13, so there is no pathological cluster requiring emergency remediation. Only 10 clusters currently have multiple members, which means the product signal exists but is sparse. A response cap of 20 is sufficient for current data and prevents unbounded growth. The existing index on `(cluster_id, collected_date)` supports the lookup (`news_collector/storage/models.py:219-236`).

### Proposed contract shape

The smallest future cross-repo addition is:

```text
cluster_id: Optional[str]
related: List[{ id, title, source, url, score }]
```

`cluster_id` would let consumers identify a transient grouping, while `related` would carry everything needed for an "also reported by" list without an additional frontend database query. The fields should be added together to the backend export contract, adapter, frontend `AstroPost` schema, and contract-sync tests. They are deliberately not implemented in this spike.

## Recommendation

Build a smaller version first: expose and observe the read-only related endpoint, then add the proposed export fields only if cluster precision and reader value are acceptable. Do not introduce a persisted master id yet. The current data has useful multi-source clusters but too few of them to justify a larger publication and frontend contract change before measuring quality.
