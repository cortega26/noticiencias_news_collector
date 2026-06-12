from __future__ import annotations

import pytest

from news_collector.editorial.council import EditorialCouncil


def _verdict(editor_approval: str, scores: list[float] | None = None):
    assessments = [
        {"role": f"role-{index}", "score": score, "observation": ""}
        for index, score in enumerate(scores or [4.0, 4.0, 4.0, 4.0])
    ]
    council = EditorialCouncil.__new__(EditorialCouncil)
    return council._parse_verdict(
        {
            "council_assessments": assessments,
            "editorial_synthesis": {},
            "editor_approval": editor_approval,
        }
    )


@pytest.mark.parametrize(
    ("editor_approval", "expected"),
    [
        ("Sí, es Noticiencias", True),
        ("No, requiere cambios", False),
        ("Sin valor periodístico, no", False),
        ("si", True),
    ],
)
def test_editor_approval_requires_explicit_affirmation(
    editor_approval: str, expected: bool
) -> None:
    assert _verdict(editor_approval).is_approved is expected


def test_editor_approval_still_requires_every_score_at_least_two() -> None:
    assert _verdict("Sí, es Noticiencias", [4.5, 4.5, 4.5, 1.0]).is_approved is False
