import json
from pathlib import Path


def test_editorial_eval_seed_is_synthetic_and_has_no_human_gold_labels():
    path = Path(__file__).parent / "data" / "editorial_eval_seed.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    assert len(rows) == 10
    assert len({row["case_id"] for row in rows}) == len(rows)
    for row in rows:
        assert row["provenance"] == "synthetic"
        assert row["source_mode"] in {"full_text", "abstract_only"}
        assert row["source_text"]
        assert row["draft_text"]
        assert row["human_review"] == {
            "status": "pending",
            "reviewer_a": None,
            "reviewer_b": None,
            "adjudicated": None,
        }
        assert row["automatic_assessments"] == []
        assert "gold" not in row
