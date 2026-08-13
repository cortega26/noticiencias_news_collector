"""Plan 048 Step 2/3 tooling tests: corpus validator + baseline evaluator.

These test the TOOLING built for the curated-enrichment-registry spike, not
enrichment quality itself. The evaluator's own determinism check replays the
6 existing `golden_articles.json` entries (already-established gold-labeled
examples used elsewhere as exact-match assertions) — this is a mechanism
check only, and is not counted as sufficient evaluation evidence, per the
plan's own Step 3 Verify line and this script's own `sufficient_evidence`
field.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import evaluate_enrichment_registry as evaluator  # noqa: E402
import validate_enrichment_corpus as validator  # noqa: E402
from news_collector.enrichment.pipeline import EnrichmentPipeline  # noqa: E402

CORPUS_PATH = REPO_ROOT / "tests" / "data" / "enrichment_eval.jsonl"
GOLDEN_PATH = REPO_ROOT / "tests" / "data" / "golden_articles.json"


def _load_corpus_records():
    return validator._load_records(CORPUS_PATH)


class TestCorpusValidator:
    def test_seed_corpus_is_structurally_valid(self):
        records = _load_corpus_records()
        errors = validator.validate(records)
        assert errors == [], errors

    def test_seed_corpus_covers_every_supported_language(self):
        records = _load_corpus_records()
        languages = {r["language"] for r in records}
        assert languages == {"en", "es", "pt", "fr"}

    def test_seed_corpus_covers_every_declared_adversarial_case_type(self):
        records = _load_corpus_records()
        case_types = {r["case_type"] for r in records}
        assert {
            "ambiguous_acronym",
            "substring",
            "negation",
            "missing_accent",
            "multi_topic",
            "hard_negative",
            "general_fallback",
        }.issubset(case_types)

    def test_duplicate_id_is_rejected(self):
        records = _load_corpus_records()
        broken = records + [dict(records[0])]
        errors = validator.validate(broken)
        assert any("duplicate id" in e for e in errors)

    def test_dev_heldout_overlap_is_rejected(self):
        records = _load_corpus_records()
        broken = [dict(r) for r in records]
        # Force an overlap: duplicate a dev record's id into the heldout split.
        dev_record = next(r for r in broken if r["split"] == "dev")
        clone = dict(dev_record)
        clone["split"] = "heldout"
        errors = validator.validate(broken + [clone])
        assert any("overlap" in e for e in errors)

    def test_invalid_language_is_rejected(self):
        records = _load_corpus_records()
        broken = [dict(r) for r in records]
        broken[0] = dict(broken[0])
        broken[0]["language"] = "de"
        errors = validator.validate(broken)
        assert any("language" in e for e in errors)

    def test_reviewed_record_with_null_gold_is_rejected(self):
        records = _load_corpus_records()
        broken = [dict(r) for r in records]
        broken[0] = dict(broken[0])
        broken[0]["review_status"] = "reviewed"
        # gold_topics/gold_entities must be explicitly nulled — the first
        # seed record is now genuinely reviewed with gold labels, so the
        # invalid state has to be manufactured.
        broken[0]["gold_topics"] = None
        broken[0]["gold_entities"] = None
        errors = validator.validate(broken)
        assert any(
            "review_status=reviewed but gold_topics is null" in e for e in errors
        )

    def test_email_like_text_is_flagged(self):
        records = _load_corpus_records()
        broken = [dict(r) for r in records]
        broken[0] = dict(broken[0])
        broken[0]["summary"] = (
            broken[0]["summary"] + " Contact tester@example.com for details."
        )
        errors = validator.validate(broken)
        assert any("email" in e for e in errors)


class TestEvaluatorDeterminism:
    """The 6 golden_articles.json entries are already-established gold
    labels (used as exact-match assertions in test_enrichment_pipeline.py),
    so treating them as 'reviewed' here for a determinism check is honest —
    it's the plan's own explicit disqualification of them as *sufficient*
    evaluation evidence that this test's assertions must still respect."""

    @staticmethod
    def _golden_as_reviewed_records():
        goldens = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        return [
            {
                "id": g["id"],
                "language": g["language"],
                "title": g["title"],
                "summary": g["summary"],
                "gold_topics": g["expected"]["topics"],
                "gold_entities": g["expected"]["entities"],
                "review_status": "reviewed",
            }
            for g in goldens
        ]

    def test_repeated_runs_are_identical_except_timing(self):
        records = self._golden_as_reviewed_records()
        pipeline = EnrichmentPipeline()

        report_a = evaluator.evaluate(records, pipeline)
        report_b = evaluator.evaluate(records, pipeline)

        report_a.pop("latency_ms")
        report_b.pop("latency_ms")
        assert report_a == report_b

    def test_six_goldens_are_explicitly_marked_insufficient_evidence(self):
        records = self._golden_as_reviewed_records()
        pipeline = EnrichmentPipeline()
        report = evaluator.evaluate(records, pipeline)

        assert report["record_count"] == 6
        assert report["sufficient_evidence"] is False
        assert "NOT sufficient evaluation evidence" in report["evidence_note"]

    def test_perfect_predictions_score_f1_one(self):
        """Sanity check the scoring math itself using gold labels set to
        exactly whatever the pipeline predicts for title+summary alone.

        Note: this deliberately does NOT reuse golden_articles.json's own
        `expected` topics directly as gold — those were authored against
        title+summary+content combined (test_enrichment_pipeline.py passes
        the full sample dict), and a real gap was found while writing this
        test: pattern-matching topics from title+summary only measurably
        undercounts some topics genuinely present in the fuller article
        (e.g. "science" is matched via a "scientists" substring that only
        appears in `content` for 4 of the 6 goldens, not their
        title/summary). That's a real characteristic of a
        title+summary-only evaluation corpus (per plan 048 Step 2's own
        "title-summary records" spec) worth knowing about, not a scoring
        bug — so this test isolates the arithmetic instead of asserting
        parity with content-dependent golden labels it cannot reach."""
        records = self._golden_as_reviewed_records()
        pipeline = EnrichmentPipeline()

        # Replace gold with the pipeline's own title+summary-only output,
        # so predicted == gold by construction and F1 must be exactly 1.0.
        for rec in records:
            result = pipeline.enrich_article(
                {"title": rec["title"], "summary": rec["summary"]}
            )
            rec["gold_topics"] = list(result["topics"])
            rec["gold_entities"] = list(result["entities"])

        report = evaluator.evaluate(records, pipeline)

        assert report["topics"]["f1"] == 1.0
        assert report["entities"]["f1"] == 1.0
        assert report["topics"]["micro_f1"] == 1.0
        assert report["entities"]["micro_f1"] == 1.0

    def test_unreviewed_seed_corpus_records_are_excluded_from_evaluation(self):
        """The evaluator must only ever score reviewed (gold-labeled)
        records — an unreviewed draft's null gold labels must never be
        silently treated as ground truth. Uses explicit fixture records
        rather than asserting the live seed corpus's review state (all 44
        seed records are now reviewed)."""
        fixture = [dict(r) for r in _load_corpus_records()[:2]]
        fixture[0] = dict(fixture[0])
        fixture[1] = dict(fixture[1])
        fixture[1]["review_status"] = "draft"
        fixture[1]["gold_topics"] = None
        fixture[1]["gold_entities"] = None
        with open(REPO_ROOT / ".hypothesis" / "tmp_eval_fixture.jsonl", "w") as fh:
            for rec in fixture:
                fh.write(json.dumps(rec) + "\n")
        try:
            loaded = evaluator._load_reviewed_records(
                REPO_ROOT / ".hypothesis" / "tmp_eval_fixture.jsonl"
            )
        finally:
            (REPO_ROOT / ".hypothesis" / "tmp_eval_fixture.jsonl").unlink(
                missing_ok=True
            )
        assert len(loaded) == 1
        assert loaded[0]["id"] == fixture[0]["id"]
