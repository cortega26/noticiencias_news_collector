"""Plan 211: source and claim integrity rules, with the real defects of the
2026-11-08 content PRs (#406, #402, #398, #391) as fixtures."""

from __future__ import annotations

from datetime import date

from news_collector.editorial.source_integrity import (
    downgrade_unattributed_certainty,
    find_name_inconsistencies,
    find_second_person_address,
    ground_sources,
    strip_leading_headline_line,
    strip_stray_hashtags,
)

SCIENCE_NEWS = "https://sciencenews.org/article/evidence-dinosaur-blood-fossilize"
ARTICLE_DATE = date(2026, 11, 6)
EVIDENCE = (
    "Tiny microstructures ... researchers report November 2 in the Proceedings of "
    "the National Academy of Sciences. See https://www.biorxiv.org/content/10.1101/xyz "
    "and the paper at doi.org/10.1073/pnas.2614248123."
)


def _ground(sources, **overrides):
    kwargs = dict(
        source_url=SCIENCE_NEWS,
        source_title="This may be the best evidence yet",
        source_publisher="Science News",
        evidence_text=EVIDENCE,
        article_date=ARTICLE_DATE,
    )
    kwargs.update(overrides)
    return ground_sources(sources, **kwargs)


# --- ground_sources ---------------------------------------------------------


def test_invented_doi_and_university_homepage_are_dropped_as_in_pr_406() -> None:
    result = _ground(
        [
            {
                "title": "This may be the best evidence yet that dinosaur blood can fossilize",
                "url": SCIENCE_NEWS,
                "publisher": "Science News",
                "date": "2024-11-02",
            },
            {
                "title": "Molecular evidence for preservation of heme",
                "url": "https://doi.org/10.1073/pnas.2407389121",
            },
            {"title": "Curtin University research", "url": "https://www.curtin.edu.au"},
        ]
    )

    assert [s["url"] for s in result.sources] == [SCIENCE_NEWS]
    assert result.dropped == [
        "https://doi.org/10.1073/pnas.2407389121",
        "https://www.curtin.edu.au",
    ]
    # The primary source's 2024 date is two years before the article.
    assert "date" not in result.sources[0]
    assert result.changed


def test_doi_present_in_the_evidence_is_kept() -> None:
    result = _ground(
        [{"title": "Paper", "url": "https://doi.org/10.1073/pnas.2614248123"}]
    )

    urls = [s["url"] for s in result.sources]
    assert "https://doi.org/10.1073/pnas.2614248123" in urls
    assert result.dropped == []


def test_url_present_in_evidence_is_kept_ignoring_scheme_www_and_query() -> None:
    result = _ground(
        [{"title": "Preprint", "url": "http://biorxiv.org/content/10.1101/xyz?rss=1"}]
    )

    assert result.dropped == []


def test_primary_source_is_added_when_every_generated_source_is_dropped() -> None:
    result = _ground([{"title": "Invented", "url": "https://example.org/made-up"}])

    assert result.primary_added
    assert result.sources == [
        {
            "title": "This may be the best evidence yet",
            "url": SCIENCE_NEWS,
            "publisher": "Science News",
        }
    ]


def test_plausible_recent_date_is_kept_and_future_or_stale_dates_are_removed() -> None:
    recent = _ground([{"title": "T", "url": SCIENCE_NEWS, "date": "2026-11-02"}])
    future = _ground([{"title": "T", "url": SCIENCE_NEWS, "date": "2026-11-09"}])
    stale = _ground([{"title": "T", "url": SCIENCE_NEWS, "date": "2024-11-02"}])
    junk = _ground([{"title": "T", "url": SCIENCE_NEWS, "date": "noviembre"}])

    assert recent.sources[0]["date"] == "2026-11-02"
    assert not recent.changed
    for result in (future, stale, junk):
        assert "date" not in result.sources[0]
        assert result.dates_removed


def test_ground_sources_does_not_mutate_its_input() -> None:
    original = [{"title": "T", "url": SCIENCE_NEWS, "date": "2024-11-02"}]

    _ground(original)

    assert original == [{"title": "T", "url": SCIENCE_NEWS, "date": "2024-11-02"}]


# --- downgrade_unattributed_certainty --------------------------------------


def test_categorical_confirmed_claims_become_uncertain_under_a_caveat() -> None:
    items, downgraded = downgrade_unattributed_certainty(
        [
            {
                "label": "Es la prueba química más antigua y sólida de sangre fosilizada",
                "status": "confirmed",
            },
            {
                "label": "La vía microbiota-AhR-microglía explica el sesgo sexual",
                "status": "confirmed",
            },
            {
                "label": "Análisis elemental detectó hierro, carbono y nitrógeno",
                "status": "confirmed",
            },
        ],
        requires_uncertainty_note=True,
    )

    assert [i["status"] for i in items] == ["uncertain", "uncertain", "confirmed"]
    assert len(downgraded) == 2


def test_no_downgrade_without_an_uncertainty_note_or_for_disputed() -> None:
    claim = [{"label": "Explica el sesgo", "status": "confirmed"}]
    items, downgraded = downgrade_unattributed_certainty(
        claim, requires_uncertainty_note=False
    )
    assert items[0]["status"] == "confirmed" and downgraded == []

    items, downgraded = downgrade_unattributed_certainty(
        [{"label": "Explica el sesgo", "status": "disputed"}],
        requires_uncertainty_note=True,
    )
    assert items[0]["status"] == "disputed" and downgraded == []


# --- body sanitizers -------------------------------------------------------


def test_inline_hashtag_is_stripped_but_headings_and_anchors_are_not() -> None:
    body = (
        "# Título\n\nPublicaciones sin la etiqueta #advancedmaternalage aquí.\n\n"
        "## Sección\n\nVer [ancla](https://x.org/p#seccion) y otra #etiqueta.\n"
    )

    cleaned, count = strip_stray_hashtags(body)

    assert "advancedmaternalage" in cleaned and "#advancedmaternalage" not in cleaned
    assert cleaned.startswith("# Título")
    assert "## Sección" in cleaned
    assert "p#seccion" in cleaned
    assert count == 2


def test_loose_bold_headline_is_removed_as_in_pr_391() -> None:
    body = (
        "**El negocio de la esperanza mitocondrial: cuando la FIV se vende como cura**\n\n"
        "Una mujer holandesa de 46 años viaja a Albania.\n"
    )

    cleaned, removed = strip_leading_headline_line(body)

    assert removed.startswith("**El negocio")
    assert cleaned.startswith("Una mujer holandesa")


def test_loose_plain_headline_is_removed_as_in_pr_398() -> None:
    body = (
        "Un interruptor oculto: Las células madre de tus huesos se adaptan a lesiones\n\n"
        "¿Te has preguntado cómo saben qué hacer?\n"
    )

    cleaned, removed = strip_leading_headline_line(body)

    assert removed is not None
    assert cleaned.startswith("¿Te has preguntado")


def test_real_lead_sentence_and_markdown_structures_are_kept() -> None:
    for body in (
        "La sangre no debería durar 115 millones de años.\n\nSegundo párrafo.\n",
        "## Sección\n\nTexto.\n",
        "- elemento\n\nTexto.\n",
        "Línea corta sin punto\nque continúa en el mismo párrafo.\n\nOtro.\n",
    ):
        cleaned, removed = strip_leading_headline_line(body)
        assert removed is None and cleaned == body


# --- advisory finders -------------------------------------------------------


def test_name_mismatch_between_frontmatter_and_body_is_flagged_as_in_pr_391() -> None:
    flagged = find_name_inconsistencies(
        ["Datos no publicados de 2019 del embriólogo Valeriy Mazur sugieren..."],
        "El embriólogo Pavlo Mazur probó la transferencia pronuclear.",
    )

    assert flagged == ["Valeriy Mazur"]


def test_consistent_or_absent_names_are_not_flagged() -> None:
    assert not find_name_inconsistencies(
        ["Pavlo Mazur lo probó"], "El embriólogo Pavlo Mazur lo probó."
    )
    assert not find_name_inconsistencies(["Kliti Grice lo dijo"], "Texto sin nombres.")


def test_second_person_address_is_reported() -> None:
    hits = find_second_person_address(
        "¿Te has preguntado cómo se reparan los huesos? Las células madre de tus huesos..."
    )

    assert {h.lower() for h in hits} == {"te has preguntado", "tus"}
    assert not find_second_person_address("Las células madre óseas se reparan.")


def test_sources_are_kept_when_there_is_no_primary_source_to_fall_back_on() -> None:
    original = [{"title": "Sin ancla", "url": "https://example.org/made-up"}]

    result = _ground(original, source_url=None, source_title=None)

    assert result.sources == original
    assert not result.changed
