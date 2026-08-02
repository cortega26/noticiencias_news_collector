# Versioned publication feed — spike document (plan 049)

> **Status**: SPIKE — not a production implementation. The direct Git/PR
> publication path remains the production control. This document and the
> accompanying prototype are decision artifacts only.

## Decision-driving use cases (Step 1)

| Use case | Current Git/PR path | Feed would help? |
|---|---|---|
| Failed PR recovery | Re-push the branch; no replay log | Marginal — Git already tracks commits |
| Multi-article atomicity | One PR per batch; partial failure leaves orphan commits | Yes — batch hash + atomic staging |
| Correction/tombstone propagation | Manual edit + republish; no tombstone | Yes — tombstone operation |
| Reproducible rollback | `git revert` works but couples to frontend FS | Marginal — feed revisions are FS-independent |
| Consumer decoupling | Frontend is the only consumer | Only if future consumers appear |
| Audit history | Git log + `refinery_manifest.json` | Marginal — Git is already an audit log |
| Publish latency | ~30s per PR (network-bound) | No improvement — feed still needs PR review |
| Future consumers | None identified | Hypothetical |

**Named consumers/operators**: Operator (editorial team). Only consumer is
the frontend Astro content collection.

**Prioritized use cases**: (1) multi-article atomicity, (2) tombstone
propagation, (3) failed PR recovery. The rest are already solved by Git +
plans 020/021/041.

**Reasons not to build a feed**: Git already provides versioning, audit
history, and rollback. A feed adds operational complexity (storage,
compaction, signing) without solving any prioritized use case that
couldn't be addressed by strengthening the existing manifest/PR flow.

## Minimal immutable contract (Step 2)

```
FeedRevision v1:
  feed_version:    1
  revision:       monotonic integer (per producer)
  parent:         previous revision number (None for initial)
  producer_commit: git SHA of the producing backend commit
  generated_at:   ISO timestamp
  operation:      upsert | tombstone
  refinery_id:    stable date-prefixed slug
  canonical_slug: public URL path component
  content_hash:   SHA-256 of frontmatter + body
  frontmatter:    full YAML frontmatter (escaped)
  body:           Markdown body (no MDX execution)
  assets:         list of { path, hash } (never fetched by prototype)
  prior_revision: for corrections, the revision being corrected
  batch_hash:     SHA-256 of all revision hashes in the same batch
```

Canonical serialization: JSON with sorted keys, no trailing whitespace.
Ordering: by `revision` (monotonic). Idempotency: same `refinery_id` +
`content_hash` = duplicate, skipped. Tombstone: requires a prior `upsert`
for the same `refinery_id`.

## Build/no-build decision (Step 6)

**Recommendation: DO NOT BUILD**

Rationale:
- Git + `refinery_manifest.json` already provides versioning, audit
  history, and rollback for the current single-consumer architecture.
- The only prioritized use case that a feed would meaningfully improve
  is multi-article atomicity — but that can be addressed more simply by
  adding a batch ID to the existing PR flow (one PR per batch, with
  manifest entries for all articles).
- Tombstones can be implemented as a frontmatter field (`status: retracted`)
  in the existing Markdown, not a separate feed operation.
- A feed would add operational complexity: storage, compaction, signing,
  consumer synchronization — all for a single consumer that is already
  well-served by Git.
- **Dependencies**: plan 041 (workspace verification) must be complete
  before any production feed could be considered, but the decision is
  DO NOT BUILD regardless.
- **Deletion date for prototype code**: retained as `tests/spikes/` for
  reference; no production code to delete.
- **Architecture owner**: Operator (editorial team).
- **Review date**: Revisit only if a second consumer is identified or
  multi-article atomicity proves insufficient with batch-PR approach.

**Next steps if revisited**:
1. Add a batch ID to the existing PR flow for multi-article atomicity.
2. Add a `status: retracted` frontmatter field for tombstones.
3. Re-evaluate a feed only if a second consumer appears.
