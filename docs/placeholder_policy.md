# Structured Placeholder Policy

The placeholder audit enforces structured TODO/FIXME/TBD markers so that each open action has an accountable owner, target date, and tracking issue. This document summarizes the policy, scoring model, and developer workflow.

## Allowed Markers

| Marker | Notes |
| --- | --- |
| `TODO` | Use in production code comments. Requires `owner`, `due`, and `issue`. |
| `FIXME` | Flag known defects. Requires `owner`, `due`, and `issue`. |
| `TBD` | Docs only; must link to an issue or live inside a fenced block. |

### Canonical examples

The samples below live inside a fenced block with linked issues, so the audit
itself skips them (see "Markdown fenced code blocks" under Blocking Rules):

```markdown
# TODO[owner=@alice; due=2027-10-31; issue=#123]: handle retries
# FIXME[owner=@bob; due=2027-11-15; issue=https://tracker/ISSUE-9]: replace stub
TBD[issue=#123]: outline future CLI
```

## Blocking Rules

* Production code (`*.py`) **must** specify `owner`, `due`, and `issue` for every placeholder.
* Any placeholder with a due date in the past is a **blocking HIGH** severity item.
* Placeholders added or modified in a PR without the full metadata triad are blocking, regardless of location.
* Markdown fenced code blocks are ignored unless the placeholder omits the `issue` field.

## Warnings

* Placeholders in `tests/**` or `examples/**` are downgraded to warnings.
* Fully structured placeholders with a due date within seven days emit a medium-severity reminder.
* Docs-only `TBD` entries with a valid issue link are tracked as low severity (for visibility but not failure).

## Scoring Model

The automated checker computes a composite score:

```
score = context_weight × completeness_weight × age_factor
```

* **Context weight:** production code = 1.0, tests/examples = 0.5, docs = 0.25.
* **Completeness:** full triad = 0; missing one field = 0.5; missing two or more fields = 1.0.
* **Age factor:** start at `1.0`; add `+0.25` if the line is older than 30 days, `+0.5` if older than 90 days.

Severity mapping:

| Score / Condition | Severity |
| --- | --- |
| `score ≥ 1.25` or missing metadata in production | HIGH |
| `0.75 ≤ score < 1.25` or due within 7 days | MED |
| Otherwise | LOW |

Expired placeholders (`due < today`) are always HIGH.

## Delta Mode

The PR audit compares changed files against `origin/main`:

* CI fails **only** when the PR introduces a **net-new HIGH** placeholder or an expired due date in the changed lines.
* Legacy HIGH items in the halo (context lines) are surfaced as warnings in the PR comment but do not fail CI.
* Nightly full scans run in non-blocking mode by default; pass `--strict` to treat any HIGH severity as fatal.

## Configuration

The checker reads `.placeholder-audit.yaml`. Defaults can be overridden if new contexts or file types are added.

| Name | Type | Default | Required | Description |
| --- | --- | --- | --- | --- |
| `include` | list[str] | `['**/*.py', '**/*.md']` | Yes | Glob patterns to include in scans. |
| `exclude` | list[str] | `['venv/**', '.venv/**', 'node_modules/**', 'dist/**', 'build/**', '**/*.min.*', '**/generated/**']` | No | Paths to ignore. |
| `contexts` | mapping[str, list[str]] | see config | Yes | Maps context names (`prod_code`, `tests`, `docs`) to glob patterns. |
| `required_fields` | list[str] | `['owner', 'due', 'issue']` | Yes | Metadata fields enforced on placeholders. |
| `due_format` | str | `YYYY-MM-DD` | Yes | Expected due date format. |
| `warn_window_days` | int | `7` | Yes | Days before due date to escalate to MED. |
| `age_threshold_days.warn` | int | `30` | Yes | Blame age (days) before applying +0.25 factor. |
| `age_threshold_days.high` | int | `90` | Yes | Blame age (days) before applying +0.5 factor. |
| `block_severities` | list[str] | `['HIGH']` | Yes | Severities that fail CI. |
| `delta_mode` | bool | `true` | Yes | Enable net-new HIGH gating. |
| `pr_halo_lines` | int | `10` | Yes | Halo lines to include around diff hunks. |

## Self-audit scope

The audit's own test data is excluded from scans in `.placeholder-audit.yaml`:

* `tests/placeholder_audit/fixtures/**` — intentionally malformed markers
  asserted by unit tests.
* `tests/placeholder_audit/test_placeholder_audit.py` — audit-pattern examples
  embedded in string literals asserted by unit tests.

The examples in this document stay inside fenced blocks with linked issues
instead of exclusions, so the documented syntax remains visible to readers
while the audit skips it by rule.

## CLI Usage

Run the audit locally before opening a pull request:

```bash
python -m tools.placeholder_audit --pr-diff-only --base origin/main --halo 10 --sarif audit.sarif --format table
```

For full repository sweeps (e.g., nightly jobs):

```bash
python -m tools.placeholder_audit --sarif audit.sarif --format json
```

Use the bundled make targets for local workflows:

```bash
make audit-todos-check  # delta mode with SARIF + PR comment artifacts
make audit-placeholders # contributor alias of audit-todos-check (CONTRIBUTING entry point)
make audit-todos        # full repository snapshot in reports/placeholders.*
```

## Outputs

* **SARIF** (`audit.sarif`) is uploaded for inline annotations.
* **PR comment** (markdown table) summarizes findings, reasons, and suggested fixes.
* A terminal summary reports counts by severity and enumerates legacy HIGH placeholders captured in the halo.

For questions or improvements, reach out in `#maintainers-news` before updating the policy.
