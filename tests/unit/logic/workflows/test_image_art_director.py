"""Plan 202: art direction for editorial hero images."""

from __future__ import annotations

import json

import pytest

from news_collector.logic.workflows.image_art_director import (
    STYLE_DIRECTION,
    build_article_context,
    direct_art,
    parse_art_direction,
    render_prompt,
)

DIRECTION = {
    "candidates": [
        {"idea": "wide orbital view", "thumbnail": 5, "fidelity": 5, "freshness": 4}
    ],
    "visual_idea": "A 1,600 km cloud streams from the flank of Arsia Mons at dawn.",
    "focal_subject": "A thin white cloud trailing west from the volcano",
    "setting": "Tharsis plateau, Mars, early morning",
    "style": "photo_editorial",
    "composition": "Oblique orbital view, volcano and cloud centred",
    "lighting_and_palette": "Low sun from the east; ochre, rust, pale blue",
    "accuracy_notes": ["Broad shield volcano, not a steep cone."],
    "avoid": ["dust storm look", "Earth-like vegetation"],
    "alt_text_es": "Nube blanca y alargada que nace en el flanco del volcán Arsia Mons, en Marte.",
}


class FakeProvider:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def generate_sync(self, prompt, system=None, json_mode=False):
        self.calls.append({"prompt": prompt, "system": system, "json_mode": json_mode})
        return self.response


def test_parses_dict_and_fenced_json():
    assert parse_art_direction(DIRECTION).style == "photo_editorial"
    fenced = "```json\n" + json.dumps(DIRECTION) + "\n```"
    assert parse_art_direction(fenced).candidates[0].thumbnail == 5


@pytest.mark.parametrize(
    "response",
    ["no json here", {**DIRECTION, "style": "neon_render"}, {"visual_idea": "x"}],
)
def test_rejects_invalid_direction(response):
    with pytest.raises(ValueError):
        parse_art_direction(response)


def test_context_uses_the_edited_article():
    context = build_article_context(
        {
            "title": "Un modelo explica una nube marciana",
            "categories": ["Astronomía"],
            "summary_points": ["Mide más de 1.600 km."],
            "glossary": [{"term": "Onda de gravedad atmosférica"}, {"x": 1}],
            "uncertainty_note": "Es un modelo, no una observación directa.",
        },
        "Cuerpo\n\n\n\ndel artículo",
    )
    assert "Titular: Un modelo explica una nube marciana" in context
    assert "- Mide más de 1.600 km." in context
    assert "Glosario: Onda de gravedad atmosférica" in context
    assert "Nota de incertidumbre" in context
    assert "Cuerpo\n\ndel artículo" in context


def test_render_prompt_carries_house_style_and_safe_area():
    prompt = render_prompt(parse_art_direction(DIRECTION))
    assert prompt.startswith(STYLE_DIRECTION["photo_editorial"])
    assert "central half of the width" in prompt
    assert "Broad shield volcano, not a steep cone." in prompt
    assert "dust storm look; Earth-like vegetation; any text" in prompt


def test_direct_art_asks_for_json_with_the_art_director_prompt():
    provider = FakeProvider(DIRECTION)
    direction = direct_art(provider, {"title": "Nube"}, "cuerpo")
    assert direction.focal_subject.startswith("A thin white cloud")
    call = provider.calls[0]
    assert call["json_mode"] is True
    assert "director de arte de Noticiencias" in call["system"]
