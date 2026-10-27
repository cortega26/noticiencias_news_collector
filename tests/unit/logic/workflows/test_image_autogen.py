"""Plan 202: automatic hero images for parked publications."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from PIL import Image
from test_image_art_director import DIRECTION, FakeProvider  # same directory

from news_collector.contracts.image_brief import ImageBriefModel
from news_collector.logic.workflows.image_art_director import IMAGE_PROMPT_V2_VERSION
from news_collector.logic.workflows.image_autogen import (
    GeneratedImage,
    ImageAutoGenerator,
    checklist_for,
    validate_hero,
)
from news_collector.logic.workflows.image_briefs import ImageBriefStore


def png(width=1600, height=900):
    stream = io.BytesIO()
    Image.new("RGB", (width, height), "orange").save(stream, format="PNG")
    return stream.getvalue()


def make_brief(slug="2026-10-24-nube-marciana", article_id="3941"):
    return ImageBriefModel(
        slug=slug,
        article_id=article_id,
        reason="missing_source_image",
        topic="Una nube marciana de 1.600 km",
        news_angle="Un modelo explica cómo se forma la nube de Arsia Mons",
        scientific_domain="astronomía",
        subject_scene="Nube alargada junto al volcán Arsia Mons",
        tone="curiosidad",
        draft_alt_text="Imagen de una nube en Marte",
        generated_prompt="Prompt v1 de prueba con suficiente longitud para validar.",
        updated_at=datetime.now(timezone.utc),
    )


def checkpoint(
    slug="2026-10-24-nube-marciana", article_id="3941", status="waiting_for_image"
):
    return SimpleNamespace(
        article_id=article_id,
        status=status,
        image_brief_slug=slug,
        draft=SimpleNamespace(
            frontmatter={"title": "Un modelo explica una nube marciana"},
            content="Cuerpo del artículo.",
        ),
    )


class FakeCheckpoints:
    def __init__(self, cps):
        self.cps = cps

    def waiting(self):
        return [(1, {})]

    def all(self, run_id):
        return {cp.article_id: cp for cp in self.cps}


class FakeTool:
    def __init__(self, content=None, error=None):
        self.content = content or png()
        self.error = error
        self.calls = []

    def generate(self, prompt, checklist, workdir):
        self.calls.append({"prompt": prompt, "checklist": checklist})
        if self.error:
            raise RuntimeError(self.error)
        return GeneratedImage(self.content, "hero.png", True, [])


def generator(tmp_path, cps, tool):
    store = ImageBriefStore(tmp_path)
    for cp in cps:
        store.save_brief(make_brief(cp.image_brief_slug, cp.article_id))
    return store, ImageAutoGenerator(
        store=store,
        checkpoints=FakeCheckpoints(cps),
        tool=tool,
        provider_factory=lambda: FakeProvider(DIRECTION),
        state_dir=tmp_path / "image-autogen",
        max_attempts=2,
    )


def test_registers_generated_image_and_releases_the_wait(tmp_path):
    tool = FakeTool()
    store, gen = generator(tmp_path, [checkpoint()], tool)
    assert gen.run_once() == 1
    assert store.ready_for_article("3941", "2026-10-24-nube-marciana")
    brief = store.load_brief("2026-10-24-nube-marciana")
    assert brief is not None and brief.generation_metadata is not None
    assert brief.image_origin == "ai_generated"
    assert brief.prompt_version == IMAGE_PROMPT_V2_VERSION
    assert brief.generated_prompt == tool.calls[0]["prompt"]
    assert brief.draft_alt_text == DIRECTION["alt_text_es"]
    assert brief.generation_metadata.tool == "codex-imagegen"
    assert "Broad shield volcano, not a steep cone." in tool.calls[0]["checklist"]
    # Ready briefs leave the queue: no second generation.
    assert gen.run_once() == 0
    assert len(tool.calls) == 1


def test_failures_are_capped_per_article(tmp_path):
    tool = FakeTool(error="quota exhausted")
    store, gen = generator(tmp_path, [checkpoint()], tool)
    assert gen.run_once() == 0
    assert gen.run_once() == 0
    assert gen.run_once() == 0
    assert len(tool.calls) == 2
    assert not store.ready_for_article("3941", "2026-10-24-nube-marciana")


def test_invalid_image_counts_as_failed_attempt(tmp_path):
    tool = FakeTool(content=png(800, 800))
    store, gen = generator(tmp_path, [checkpoint()], tool)
    assert gen.run_once() == 0
    assert gen.attempts("2026-10-24-nube-marciana") == 1
    assert not store.ready_for_article("3941", "2026-10-24-nube-marciana")


def test_failing_article_does_not_block_the_next(tmp_path):
    first = checkpoint("2026-10-23-malaria", "4021")
    second = checkpoint()
    tool = FakeTool()
    store, gen = generator(tmp_path, [first, second], tool)
    store.brief_path("2026-10-23-malaria").unlink()  # first brief missing
    assert gen.run_once() == 1
    assert store.ready_for_article("3941", "2026-10-24-nube-marciana")


def test_only_waiting_checkpoints_are_considered(tmp_path):
    _, gen = generator(tmp_path, [checkpoint(status="ready")], FakeTool())
    assert gen.pending() == []


@pytest.mark.parametrize("size", [(1000, 562), (1600, 1600), (1600, 600)])
def test_validate_hero_rejects_small_or_non_landscape(size):
    with pytest.raises(ValueError):
        validate_hero(png(*size))


def test_validate_hero_accepts_codex_output_size():
    assert validate_hero(png(1672, 941)) == (1672, 941)


def test_checklist_includes_safe_area_and_no_text():
    from news_collector.logic.workflows.image_art_director import parse_art_direction

    items = checklist_for(parse_art_direction(DIRECTION))
    assert any("central half" in i for i in items)
    assert any("no text" in i for i in items)
    assert "It does not show: dust storm look" in items


# -- CodexImageTool with a fake `codex` binary ---------------------------------


def fake_codex(tmp_path, body):
    script = tmp_path / "bin" / "codex"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(0o755)
    return str(script)


def write_png_script(review):
    data = png().hex()
    return (
        'dir=""; while [ $# -gt 0 ]; do [ "$1" = "-C" ] && dir="$2"; shift; done\n'
        f"printf '{data}' | xxd -r -p > \"$dir/hero.png\"\n"
        + (f"printf '%s' '{review}' > \"$dir/review.json\"\n" if review else "")
    )


def test_codex_tool_returns_image_and_review(tmp_path):
    from news_collector.logic.workflows.image_autogen import CodexImageTool

    binary = fake_codex(
        tmp_path, write_png_script('{"passed": false, "issues": ["cone"]}')
    )
    work = tmp_path / "work"
    work.mkdir()
    image = CodexImageTool(binary, 60).generate("prompt", ["a", "b"], work)
    assert validate_hero(image.content) == (1600, 900)
    assert image.passed_review is False and image.issues == ["cone"]
    assert (work / "checklist.txt").read_text() == "a\nb"
    assert (work / "prompt.txt").read_text() == "prompt"


def test_codex_tool_without_review_is_unreviewed(tmp_path):
    from news_collector.logic.workflows.image_autogen import CodexImageTool

    binary = fake_codex(tmp_path, write_png_script(None))
    work = tmp_path / "work"
    work.mkdir()
    assert CodexImageTool(binary, 60).generate("p", [], work).passed_review is False


def test_codex_tool_fails_without_image(tmp_path):
    from news_collector.logic.workflows.image_autogen import CodexImageTool

    binary = fake_codex(tmp_path, "echo 'usage limit reached' >&2; exit 1\n")
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(RuntimeError, match="usage limit"):
        CodexImageTool(binary, 60).generate("p", [], work)


def test_codex_tool_requires_the_binary(tmp_path):
    from news_collector.logic.workflows.image_autogen import CodexImageTool

    with pytest.raises(RuntimeError, match="not found"):
        CodexImageTool("no-such-codex-binary", 60).generate("p", [], tmp_path)


def test_validate_hero_rejects_non_images():
    with pytest.raises(ValueError, match="not a readable image"):
        validate_hero(b"not an image")


def test_review_issues_do_not_block_registration(tmp_path):
    class ReviewedTool(FakeTool):
        def generate(self, prompt, checklist, workdir):
            super().generate(prompt, checklist, workdir)
            return GeneratedImage(self.content, "hero.png", False, ["cone shape"])

    store, gen = generator(tmp_path, [checkpoint()], ReviewedTool())
    assert gen.run_once() == 1
    assert store.ready_for_article("3941", "2026-10-24-nube-marciana")


def test_background_loop_runs_and_stops(tmp_path):
    import threading

    from news_collector.logic.workflows.image_autogen import start_autogen_thread

    calls = []
    stop = threading.Event()

    class Gen:
        def run_once(self):
            calls.append(1)
            stop.set()
            raise RuntimeError("scan failed")  # logged, loop survives until stop

    thread = start_autogen_thread(Gen(), stop, 1)  # type: ignore[arg-type]
    thread.join(timeout=5)
    assert calls == [1] and not thread.is_alive()
