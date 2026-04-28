from __future__ import annotations

from news_collector.scoring.pre_scorer import PreScorer


class FakeLLM:
    def __init__(self, response):
        self.model = "fake-llm"
        self._response = response

    def generate_sync(self, **kwargs):
        return self._response


def _candidate(title: str, summary: str) -> dict[str, str]:
    return {
        "title": title,
        "summary": summary,
        "url": f"https://example.com/{abs(hash(title))}",
    }


def test_prescorer_parses_reasoning_plus_json_payload() -> None:
    candidates = [
        _candidate("Campus award announced", "Dean celebrates a local student prize."),
        _candidate(
            "Chilean astronomers detect unusual signal",
            "Researchers in Chile report new evidence from a major observatory.",
        ),
        _candidate(
            "New climate study maps drought risk in Latin America",
            "A regional study quantifies drought exposure across multiple countries.",
        ),
    ]

    llm = FakeLLM("""Okay, let's tackle this carefully.

```json
{"selected_indices": [0, 2]}
```""")

    scorer = PreScorer(llm_client=llm)
    selected = scorer.select_top_candidates(candidates, limit=2, source_context="demo")

    assert [item["title"] for item in selected] == [
        "Campus award announced",
        "New climate study maps drought risk in Latin America",
    ]


def test_prescorer_invalid_llm_response_falls_back_to_editorial_rank_not_fifo() -> None:
    candidates = [
        _candidate(
            "University office announces alumni breakfast",
            "A campus office shared an update about an internal alumni breakfast.",
        ),
        _candidate(
            "Vice provost wins regional leadership award",
            "An institutional profile about a local administrative award.",
        ),
        _candidate(
            "Mexican researchers develop low-cost dengue warning model",
            "The study could help public-health teams anticipate outbreaks in Latin America.",
        ),
    ]

    scorer = PreScorer(llm_client=FakeLLM("No JSON here, just rambling text."))
    selected = scorer.select_top_candidates(candidates, limit=1, source_context="demo")

    assert (
        selected[0]["title"]
        == "Mexican researchers develop low-cost dengue warning model"
    )


def test_prescorer_partial_llm_result_is_completed_with_editorial_rank() -> None:
    candidates = [
        _candidate(
            "Campus dining hall expands spring menu",
            "A university operations update with limited public-interest value.",
        ),
        _candidate(
            "Brazil study links heat waves to productivity losses",
            "Researchers quantify how extreme heat is affecting labor conditions.",
        ),
        _candidate(
            "Peru glacier monitoring reveals accelerated ice loss",
            "Scientists warn about water-security risks for Andean communities.",
        ),
        _candidate(
            "Office of student life launches mentorship portal",
            "An internal student-services announcement.",
        ),
    ]

    scorer = PreScorer(
        llm_client=FakeLLM('{"selected_indices": [0]}'),
    )
    selected = scorer.select_top_candidates(candidates, limit=3, source_context="demo")

    assert [item["title"] for item in selected] == [
        "Campus dining hall expands spring menu",
        "Brazil study links heat waves to productivity losses",
        "Peru glacier monitoring reveals accelerated ice loss",
    ]
