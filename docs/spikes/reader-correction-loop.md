# Reader correction loop — spike document (plan 047)

> **Status**: SPIKE — not a production implementation. No production endpoint,
> queue, content, or real reporter record is changed. This document and the
> accompanying contract prototype are decision artifacts only.

## Owner and current workflow (Step 1)

- **Triage owner**: Operator (editorial team). Reports arrive via the
  frontend `ReportForm.astro` → Worker `workers/src/handlers/report.ts`
  → optional R2/email delivery (plan 023).
- **Current volume/quality**: Not measured in this spike — the report
  endpoint is production-disabled pending operator R2/KV provisioning
  (plan 023 PARTIAL status).
- **Current correction workflow**: Manual. An editor receives a report,
  reviews the article, edits the Markdown directly, and republishes via
  the Refinery PR flow. No visible correction record is emitted; readers
  cannot see what changed or why.
- **Top failure modes**: (1) reports lost when email delivery fails,
  (2) no correlation between a report and the published article's stable
  identity, (3) no visible correction note for transparency, (4) no
  deduplication of reports about the same issue.
- **Unanswered questions**: What is the acceptable response time? Who has
  authority to reject vs. accept? Is reporter consent for attribution
  required?

## Lifecycle contract (Step 2)

Versioned report/correction envelope:

```
ReportEnvelope v1:
  report_id:         opaque UUID (generated at intake)
  public_url:       normalized canonical URL (from the report)
  refinery_id:       resolved stable publication identity (from backend)
  content_revision: hash of the article content at report time
  type:             factual_error | typo | broken_link | outdated | other
  description:      bounded text (max 2000 chars)
  evidence_refs:    optional list of URLs (never fetched by the prototype)
  consent:          { contact_allowed: bool, attribution_allowed: bool }
  contact:          optional email (separated from public fields)
  timestamps:       { created, triaged?, decided?, corrected?, closed? }
  idempotency_key:  hash(public_url + type + content_revision)
  status:           received → triaged → duplicate|rejected|accepted
                   → correction_proposed → correction_published → closed
  events:           append-only list of { timestamp, actor, action, reason }
```

Allowed transitions:
- `received → triaged` (operator acknowledges)
- `triaged → duplicate` (links to existing report on same issue)
- `triaged → rejected` (with reason)
- `triaged → accepted` (with reason)
- `accepted → correction_proposed` (PR created)
- `correction_proposed → correction_published` (PR merged, plan 021 callback)
- `correction_published → closed` (operator confirms)

Disallowed: skip triage, close before correction_published, edit after closed.

## Privacy and abuse analysis (Step 3)

| Threat | Mitigation |
|---|---|
| Spam/flooding | Idempotency key + rate limit per IP/URL |
| Malicious evidence links | Evidence refs are never fetched by the prototype; displayed as text only |
| HTML/log injection | All user-supplied text is escaped before logging/display |
| Forged article identity | `refinery_id` is resolved from the backend, not trusted from the user |
| Reporter harassment | Contact field is separated from public fields; never exposed without consent |
| Sensitive-health claims | Type field does not categorize content sensitivity; all reports treated equally |
| PII access | Contact email is stored only for the report lifecycle; deleted on closure |
| Deletion requests | Reports can be deleted by operator; correction record retains only non-PII fields |
| Queue enumeration | Report IDs are opaque UUIDs, not sequential |

Data minimization: only `report_id`, `public_url`, `refinery_id`, `type`,
`description`, `evidence_refs`, `consent`, `timestamps`, `status`, `events`
are retained in the correction record. `contact` is deleted on closure.

## Build/no-build decision (Step 6)

**Recommendation: INTEGRATE (not build from scratch)**

Rationale:
- The workspace already has the building blocks: `ReportForm.astro`,
  Worker report handler, `PublicationIdentityResolver`, plan 021's
  publication callback contract.
- The smallest option meeting the need is to extend the existing Worker
  handler to emit a `correction_proposed` event when a report is
  accepted, and extend plan 021's callback to close the loop when the
  correction PR is published.
- A first-party queue is over-engineering for the current (unmeasured)
  report volume; a lightweight issue tracker integration (e.g., GitHub
  Issues) is the middle ground.
- **Dependencies**: plan 023 must complete (R2/KV provisioning) before
  any production intake; plan 021's callback must be wired to close
  correction records on PR merge.
- **Estimated work**: 2-3 days for the contract + state machine + Worker
  integration; 1-2 days for the visible correction note HTML fixture.
- **Review date**: After plan 023 reaches DONE and the operator confirms
  R2/KV provisioning.

**Next steps if approved**:
1. Implement the `ReportEnvelope` contract as a Pydantic model in
   `news_collector/contracts/`.
2. Extend the Worker handler to persist the envelope in R2 with the
   idempotency key.
3. Add a `correction_published` webhook event to plan 021's callback.
4. Prototype the visible correction note as an Astro component.
