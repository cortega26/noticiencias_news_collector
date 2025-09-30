# Contributing to Noticiencias News Collector

Thanks for helping us keep the Noticiencias stack healthy! This document captures a few ground rules that are easy to miss when touching scoring logic or fixtures.

## Local setup checklist

1. Create a virtual environment and install dependencies with hash checking:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install --require-hashes -r requirements.lock
   ```
2. Before sending a PR run:
   ```bash
   pytest
   ruff check src tests
   mypy src
   ```
3. Use descriptive commits and keep diffs focused. Every behavioural change should include a matching test.

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

## Pull request hygiene

- Keep PR descriptions action-oriented (what changed + why).
- Link related tickets or incident reports when applicable.
- Run `make format` if the CI formatter complains.
- Observe our security policy: never commit credentials or raw PII.

Happy shipping! 🚀
