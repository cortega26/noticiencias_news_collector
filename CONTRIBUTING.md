<!-- markdownlint-disable -->
# Contributing to Noticiencias News Collector

Thanks for helping us keep the Noticiencias stack healthy! This document captures the conventions reviewers expect you to follow from the first commit to the final PR.

## Coding standards

- Target **Python 3.10+** and keep functions annotated. Use `TypedDict`, `Protocol`, or dataclasses when sharing structures across modules.
- Follow **PEP 8** plus `ruff` defaults for style. Keep `structlog`-style dictionaries in logging statements with `trace_id`, `source_id`, and `article_id`.
- Keep Makefile recipes tab-indented; `make lint` now fails fast if spaces sneak into command lines.
- Persist and compare timestamps in **UTC**; convert to `America/Santiago` only inside presentation layers.
- Never swallow exceptions—wrap them with context and re-raise so the DLQ/runbooks have usable breadcrumbs.

## Quality gate checklist

1. Create a virtual environment and install dependencies with hash checking:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install --require-hashes -r requirements.lock
   ```
2. Before sending a PR run the full quality suite:
   ```bash
   pytest
   ruff check src tests
   mypy src
   ```
   Use `make test` or `make check` if you prefer a single wrapper.
3. Keep CI green by updating fixtures or type stubs when a dependency bump changes behaviour.

### Structured placeholders

- Use the structured placeholder format documented in [`docs/placeholder_policy.md`](docs/placeholder_policy.md). Every `TODO`/`FIXME` in production code **must** include `owner`, `due` (`YYYY-MM-DD`), and `issue` metadata.
- Docs may only contain `TBD[issue=…]` entries inside fenced code blocks or when directly linking to an issue.
- Before sending a PR run the diff-aware audit to catch missing metadata:
  ```bash
  make audit-placeholders
  ```
- The audit reads `.placeholder-audit.yaml`; update the config and docs together if you extend the policy.

## Commit conventions

- Prefer the imperative mood in commit subject lines (`Add reranker decay flag`, not `Added` or `Adds`).
- Reference tickets or incidents in the body when relevant and explain *why* the change exists.
- Squash noisy WIP commits before opening a PR; reviewers expect focused diffs with matching tests.

## Updating golden scoring data

When you intentionally change the scoring logic, refresh the regression fixtures so other contributors understand the delta:

1. Inspect the drift between the baseline and your branch:
   ```bash
   python scripts/score_delta.py --dataset tests/data/scoring_golden.json
   ```
   The command reports precision@K against the stored baseline along with coverage of previously surfaced articles.
2. If the differences are expected, regenerate the golden file using a frozen timestamp (keeps tests deterministic):
   ```bash
   python - <<'PY'
   from datetime import datetime, timezone
   import json
   from pathlib import Path
   from types import SimpleNamespace

   from src.scoring import feature_scorer
   from src.scoring.feature_scorer import FeatureBasedScorer

   data_path = Path("tests/data/scoring_golden.json")
   payload = json.loads(data_path.read_text(encoding="utf-8"))
   frozen_at = datetime.now(timezone.utc)

   class Frozen(datetime):
       @classmethod
       def now(cls, tz=None):
           return frozen_at.astimezone(tz) if tz else frozen_at

   feature_scorer.datetime = Frozen

   scorer = FeatureBasedScorer()
   articles = payload["articles"]
   for item in articles:
       article = SimpleNamespace(**item["article"])
       score = scorer.score_article(article)
       item["expected"].update(
           final_score=score["final_score"],
           should_include=score["should_include"],
           components=score["components"],
           penalties=score["penalties"],
       )
   payload["frozen_at"] = frozen_at.isoformat().replace("+00:00", "Z")
   data_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
   PY
   ```
3. Commit the regenerated fixture together with the code change so CI and reviewers see the expected impact.

## Refreshing other fixtures

- Collector and enrichment fixtures live in `tests/data/`. Run the helper scripts in `docs/fixtures.md` to regenerate them after intentional pipeline changes.
- Document fixture updates in the PR description so on-call engineers can match runbook expectations.

## Pull request hygiene

- Keep PR descriptions action-oriented (what changed + why).
- Link related tickets or incident reports when applicable.
- Run `make format` if the CI formatter complains.
- Observe our security policy: never commit credentials or raw PII.

Happy shipping! 🚀
