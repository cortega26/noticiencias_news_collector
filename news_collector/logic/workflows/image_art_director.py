"""Plan 202: art direction for editorial hero images.

An LLM reads the finished Spanish article and returns one concrete visual
concept (`ArtDirection`); `render_prompt` turns it into the image-model prompt
with one of the house styles. Pure apart from the injected provider.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "editorial" / "prompts"
ART_DIRECTOR_PROMPT_PATH = PROMPTS_DIR / "editorial_image_art_director_v2.md"
IMAGE_PROMPT_V2_PATH = PROMPTS_DIR / "editorial_image_prompt_v2.md"
IMAGE_PROMPT_V2_VERSION = "editorial-image-v2"

HouseStyle = Literal[
    "photo_editorial", "scientific_illustration", "conceptual_still_life"
]

# Fixed house styles keep the site visually consistent across articles.
STYLE_DIRECTION: dict[str, str] = {
    "photo_editorial": (
        "Editorial documentary photograph for a premium science magazine cover"
        " story. Real camera and lens behaviour, natural light, believable"
        " textures, restrained colour grading."
    ),
    "scientific_illustration": (
        "Hand-painted digital scientific illustration in the style of a"
        " high-end science journal feature plate: visible gouache and"
        " watercolour texture, matte surfaces, soft diffuse light,"
        " anatomically and physically correct forms, restrained palette."
        " Not a 3D render: no specular highlights, no glossy or wet-looking"
        " surfaces, no glow, no floating sparkles or particles."
    ),
    "conceptual_still_life": (
        "Conceptual still-life photograph for a magazine opener: a few real,"
        " well-crafted objects that embody the idea, studio light with soft"
        " shadows, clean background, tactile materials."
    ),
}

MAX_BODY_CHARS = 6000


class Candidate(BaseModel):
    idea: str = Field(min_length=5)
    thumbnail: int = Field(ge=1, le=5)
    fidelity: int = Field(ge=1, le=5)
    freshness: int = Field(ge=1, le=5)


class ArtDirection(BaseModel):
    candidates: list[Candidate] = Field(default_factory=list)
    visual_idea: str = Field(min_length=15)
    focal_subject: str = Field(min_length=10)
    setting: str = Field(min_length=5)
    style: HouseStyle
    composition: str = Field(min_length=10)
    lighting_and_palette: str = Field(min_length=10)
    accuracy_notes: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    alt_text_es: str = Field(min_length=20, max_length=220)


def build_article_context(frontmatter: dict[str, Any], body: str) -> str:
    """What the art director reads: the edited article, not the raw source."""
    lines = [f"Titular: {frontmatter.get('title', '')}"]
    if frontmatter.get("excerpt"):
        lines.append(f"Bajada: {frontmatter['excerpt']}")
    categories = frontmatter.get("categories") or []
    if categories:
        lines.append(f"Sección: {', '.join(map(str, categories))}")
    points = frontmatter.get("summary_points") or []
    if points:
        lines.append("Puntos clave:")
        lines.extend(f"- {p}" for p in points)
    glossary = frontmatter.get("glossary") or []
    terms = [str(g["term"]) for g in glossary if isinstance(g, dict) and g.get("term")]
    if terms:
        lines.append(f"Glosario: {', '.join(terms)}")
    if frontmatter.get("uncertainty_note"):
        lines.append(f"Nota de incertidumbre: {frontmatter['uncertainty_note']}")
    text = re.sub(r"\n{3,}", "\n\n", body).strip()[:MAX_BODY_CHARS]
    lines.extend(["", "Cuerpo del artículo:", text])
    return "\n".join(lines)


def parse_art_direction(response: Any) -> ArtDirection:
    """Accept a dict or a JSON string (optionally fenced); raise ValueError."""
    data = response
    if isinstance(response, str):
        match = re.search(r"\{.*\}", response, re.S)
        if not match:
            raise ValueError("Art direction response has no JSON object")
        data = json.loads(match.group(0))
    try:
        return ArtDirection.model_validate(data)
    except ValidationError as err:
        raise ValueError(f"Invalid art direction: {err}") from err


def direct_art(provider: Any, frontmatter: dict[str, Any], body: str) -> ArtDirection:
    system = ART_DIRECTOR_PROMPT_PATH.read_text(encoding="utf-8")
    response = provider.generate_sync(
        build_article_context(frontmatter, body), system=system, json_mode=True
    )
    return parse_art_direction(response)


def _sentence(items: list[str], fallback: str) -> str:
    cleaned = [i.strip().rstrip(".") for i in items if i and i.strip()]
    return "; ".join(cleaned) + "." if cleaned else fallback


def render_prompt(direction: ArtDirection) -> str:
    template = IMAGE_PROMPT_V2_PATH.read_text(encoding="utf-8")
    return template.format(
        style_direction=STYLE_DIRECTION[direction.style],
        visual_idea=direction.visual_idea.strip(),
        focal_subject=direction.focal_subject.strip(),
        setting=direction.setting.strip(),
        composition=direction.composition.strip().rstrip(".") + ".",
        lighting_and_palette=direction.lighting_and_palette.strip(),
        accuracy_notes=_sentence(direction.accuracy_notes, "Faithful to the article."),
        avoid=_sentence(direction.avoid, "generic stock imagery").rstrip("."),
    ).strip()
