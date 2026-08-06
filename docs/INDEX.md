# docs/ — Index

**Status:** Active  
**Authority:** Subordinate to `docs/SOURCE_OF_TRUTH.md`

This index helps you find the right document quickly. For the canonical authority chain
and the rules for which file wins when docs and code disagree, see `docs/SOURCE_OF_TRUTH.md`.

---

## Start here

| I want to… | Read |
|---|---|
| Set up the full system locally (both repos) | [`RUNBOOK_LOCAL_DEV.md`](RUNBOOK_LOCAL_DEV.md) |
| Understand engineering governance and change rules | [`AGENTS.md`](AGENTS.md) |
| Trace an article from RSS to live page | [`PRODUCT_FLOW.md`](PRODUCT_FLOW.md) |
| Understand cross-repo contract shapes and failure semantics | [`PIPELINE_CONTRACTS.md`](PIPELINE_CONTRACTS.md) |
| Understand the back-end package map and dependency direction | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| Know which files win when docs and code disagree | [`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md) |
| Recover from an operational incident | [`runbook.md`](runbook.md) |
| Debug a specific collector issue | [`collector_runbook.md`](collector_runbook.md) |
| Understand CI workflows and gates | [`ci.md`](ci.md) |

---

## Reference — operational

| Topic | Document |
|---|---|
| All configuration fields and their defaults | [`config_fields.md`](config_fields.md) |
| API usage examples | [`api_examples.md`](api_examples.md) |
| Common output format across pipeline stages | [`common_output_format.md`](common_output_format.md) |
| Contract inventory (all typed boundaries) | [`contracts_inventory.md`](contracts_inventory.md) |
| Database deployment (SQLite → PostgreSQL) | [`database_deployment.md`](database_deployment.md) |
| Editorial modes (cognitive, basic, pattern) | [`EDITORIAL_MODES.md`](EDITORIAL_MODES.md) |
| Editorial quality system | [`editorial_quality_system.md`](editorial_quality_system.md) |
| FAQ (common errors and fixes) | [`faq.md`](faq.md) |
| Fixture management for tests | [`fixtures.md`](fixtures.md) |
| Healthcheck runbook | [`runbooks/healthcheck.md`](runbooks/healthcheck.md) |
| Operations reference | [`operations.md`](operations.md) |
| Ops runbook (alerts and incidents) | [`runbook.md`](runbook.md) |
| Performance baselines | [`performance_baselines.md`](performance_baselines.md) |
| Placeholder policy (TODO/FIXME standards) | [`placeholder_policy.md`](placeholder_policy.md) |
| Release checklist | [`release-checklist.md`](release-checklist.md) |
| Release notes | [`release_notes.md`](release_notes.md) |
| Security policy | [`security.md`](security.md) |
| Security removal plan | [`security_removal_plan.md`](security_removal_plan.md) |
| Testing strategy and test taxonomy | [`testing.md`](testing.md) |
| Tools audit findings | [`tools_audit_issues.md`](tools_audit_issues.md) |

---

## Reference — development

| Topic | Document |
|---|---|
| Active development backlog | [`dev/BACKLOG.md`](dev/BACKLOG.md) |
| Quality baseline and current metrics | [`dev/QUALITY_BASELINE.md`](dev/QUALITY_BASELINE.md) |
| Quality checklist | [`dev/QUALITY.md`](dev/QUALITY.md) |
| Refactor plan | [`dev/REFACTOR_PLAN.md`](dev/REFACTOR_PLAN.md) |
| Static analysis findings | [`dev/STATIC_ANALYSIS.md`](dev/STATIC_ANALYSIS.md) |
| Test gaps | [`dev/TEST_GAPS.md`](dev/TEST_GAPS.md) |
| PR plan | [`dev/pr_plan.md`](dev/pr_plan.md) |
| Source-of-truth backlog | [`dev/source-of-truth-backlog.md`](dev/source-of-truth-backlog.md) |

---

## Architecture Decision Records

| ADR | Decision |
|---|---|
| [`adr/0001-adapter-pattern-contracts.md`](adr/0001-adapter-pattern-contracts.md) | Adapter pattern as the only shape-conversion choke point |
| [`adr/0002-hash-pinned-lockfiles.md`](adr/0002-hash-pinned-lockfiles.md) | Hash-pinned dependency lockfiles for reproducible builds |
| [`adr/0003-two-repo-split-and-schema-versioning.md`](adr/0003-two-repo-split-and-schema-versioning.md) | Two-repo split and cross-repo schema versioning strategy |
| [`adr/0005-completed-is-scoring-state-not-publication.md`](adr/0005-completed-is-scoring-state-not-publication.md) | `completed` is a scoring state; publication proof lives in `published_url`/`published_at` |

---

## Audit artifacts

These are historical audit records. They are useful as context but are **not** the operational
source of truth for current architecture or behavior. If any audit finding conflicts with
`ARCHITECTURE.md`, `AGENTS.md`, or `PIPELINE_CONTRACTS.md`, the live governance docs win.

| File/Folder | Contents |
|---|---|
| `audits/` | System audits (structure, quality, correctness, UX, ops) |
| `reports/` | Deduplication and audit reports |
| `SPRINT_B_REPORT.md` | Sprint B outcome summary |
| `archive/` | Archived refactor artifacts |
| `CHANGELOG.md` | Docs-layer changelog (see repo-root `CHANGELOG.md` for releases) |

---

## AI-generated and exploration docs

One-off exploration notes and prompt templates — not binding:

| File | Contents |
|---|---|
| `prompts/5_new_features.md` | Feature exploration prompts |
| `prompts/quickest5.md` | Quick-win prompt templates |
| `strategic_features.md` | Feature roadmap exploration |
| `refinery_stage3_push_collision_fix.md` | Investigation note for Stage 3 push collision fix |
