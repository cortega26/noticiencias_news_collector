"""Unit tests for title+summary MinHash grouping (Plan 111, Step 2).

Golden cases: three cross-source near-duplicates of one finding group
with the first-ranked as master; two distinct-but-topically-similar
stories stay separate; degenerate inputs never group and never raise.
"""

from news_collector.utils.similarity import group_similar_articles


def _nasa_variants():
    base_title = "NASA confirms liquid water reservoir beneath the Martian south pole"
    base_summary = (
        "Radar measurements from the Mars orbiter reveal a stable body of "
        "liquid water trapped beneath layered ice deposits near the planet south "
        "pole, renewing the debate about habitable environments on Mars today."
    )
    return [
        {"id": 1, "title": base_title, "summary": base_summary},
        {
            "id": 2,
            "title": "Liquid water lake detected under Mars south polar ice",
            "summary": (
                "Orbiter radar data point to a persistent reservoir of liquid "
                "water locked under thick ice layers at the Martian south "
                "pole, reopening questions about present-day habitability."
            ),
        },
        {
            "id": 3,
            "title": "Reservorio de agua líquida bajo el polo sur de Marte",
            "summary": (
                "Las mediciones del radar del orbitador muestran agua líquida "
                "estable bajo los hielos del polo sur marciano y reavivan el "
                "debate sobre ambientes habitables en Marte."
            ),
        },
    ]


def test_cross_source_duplicates_form_one_group() -> None:
    groups = group_similar_articles(_nasa_variants()[:2])
    assert len(groups) == 1
    (group,) = groups
    assert group.master_id == 1
    assert group.member_ids == (1, 2)
    assert group.confidence >= 0.30
    assert group.group_id.startswith("sim-")


def test_distinct_stories_stay_separate() -> None:
    items = [
        {
            "id": 1,
            "title": "New Alzheimer blood test shows promise in trials",
            "summary": "A plasma biomarker panel detected early Alzheimer pathology.",
        },
        {
            "id": 2,
            "title": "Fusion ignition milestone repeated at national facility",
            "summary": "Laser-driven implosion exceeded breakeven for the third run.",
        },
    ]
    assert group_similar_articles(items) == []


def test_same_topic_different_finding_stays_separate() -> None:
    """The critical false-positive guard: same planet, different story."""
    items = [
        {
            "id": 1,
            "title": "Perseverance rover collects new rock sample in Jezero crater",
            "summary": "The sample tube was sealed and cached for a future return mission.",
        },
        {
            "id": 2,
            "title": "Ingenuity helicopter completes final flight on Mars",
            "summary": "After dozens of flights the rotorcraft will serve as a weather station.",
        },
    ]
    assert group_similar_articles(items) == []


def test_grouping_is_deterministic() -> None:
    items = _nasa_variants()[:2]
    first = group_similar_articles(items)
    second = group_similar_articles(list(reversed(items)))
    assert first[0].group_id == second[0].group_id
    # Master follows input (ranked) order, not id order.
    assert second[0].master_id == 2


def test_degenerate_inputs_never_group_or_raise() -> None:
    assert group_similar_articles([]) == []
    assert group_similar_articles([{"id": 1}]) == []
    assert group_similar_articles([{"id": 1}, {"id": "x"}]) == []
    assert (
        group_similar_articles(
            [
                {"id": 1, "title": "  ", "summary": None},
                {"id": 2, "title": "", "summary": ""},
            ]
        )
        == []
    )
    single = group_similar_articles(
        [{"id": 1, "title": "Solo story", "summary": "nothing similar here"}]
    )
    assert single == []
