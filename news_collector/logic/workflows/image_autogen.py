"""Plan 202: automatic hero images for publications waiting for one.

For each checkpoint parked in ``waiting_for_image``, the art director reads the
edited draft, Codex imagegen (the operator's ChatGPT login) draws the image and
reviews it against the article's accuracy notes, and the result is registered
through ``ImageBriefStore.stage_upload`` as ``ai_generated``. The existing
reconciler then resumes the publication. Attempts per article are capped and
persisted so a failing article cannot drain the plan's image quota.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess  # nosec B404 - fixed argv, no shell, operator-owned binary
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from news_collector.contracts.image_brief import ImageGenerationMetadata
from news_collector.logic.workflows.image_art_director import (
    IMAGE_PROMPT_V2_VERSION,
    ArtDirection,
    direct_art,
    render_prompt,
)
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)

MIN_WIDTH = 1200
MIN_ASPECT, MAX_ASPECT = 1.6, 1.9
TOOL_NAME = "codex-imagegen"

CODEX_INSTRUCTIONS = """\
Usa tu herramienta de generación de imágenes (imagegen) para crear UNA imagen
apaisada 16:9 con el prompt completo del archivo prompt.txt, sin modificarlo.

Después revisa la imagen que generaste contra la lista de checklist.txt (una
condición por línea). Si alguna condición no se cumple, genera la imagen UNA
sola vez más, con el mismo prompt más una frase que corrija el problema, y
revisa de nuevo. No hagas más de dos generaciones en total.

Guarda la imagen final en este directorio como hero.png (cópiala desde donde
la herramienta la guarde) y escribe review.json con este formato exacto:
{"passed": true o false, "generations": 1 o 2, "issues": ["problemas que sigan presentes"]}
No hagas nada más.
"""


class ImageTool(Protocol):
    def generate(
        self, prompt: str, checklist: list[str], workdir: Path
    ) -> "GeneratedImage": ...


@dataclass(frozen=True)
class GeneratedImage:
    content: bytes
    filename: str
    passed_review: bool
    issues: list[str]


def checklist_for(direction: ArtDirection) -> list[str]:
    return [
        *direction.accuracy_notes,
        f"The main subject is clearly visible: {direction.focal_subject}",
        "The focal point that tells the story sits inside the central half of"
        " the width; backgrounds and textures may fill the frame.",
        "There is no text, letter, number, label, logo or watermark.",
        *(f"It does not show: {item}" for item in direction.avoid),
    ]


def validate_hero(content: bytes) -> tuple[int, int]:
    """Landscape, wide enough for the 1200 px social card; raise ValueError."""
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
    except (UnidentifiedImageError, OSError) as err:
        raise ValueError("Generated file is not a readable image") from err
    if width < MIN_WIDTH:
        raise ValueError(f"Generated image is {width}px wide; need {MIN_WIDTH}px")
    if not MIN_ASPECT <= width / height <= MAX_ASPECT:
        raise ValueError(f"Generated image ratio {width}x{height} is not ~16:9")
    return width, height


def _save_log(workdir: Path, stdout: Any, stderr: Any) -> None:
    def text(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", "replace")
        return value or ""

    (workdir / "codex.log").write_text(
        text(stdout) + "\n--- stderr ---\n" + text(stderr), encoding="utf-8"
    )


class CodexImageTool:
    """Runs ``codex exec`` in an isolated scratch directory."""

    def __init__(self, codex_bin: str = "codex", timeout_seconds: int = 900):
        self.codex_bin = codex_bin
        self.timeout_seconds = timeout_seconds

    def generate(
        self, prompt: str, checklist: list[str], workdir: Path
    ) -> GeneratedImage:
        binary = shutil.which(self.codex_bin)
        if binary is None:
            raise RuntimeError(f"Codex CLI not found: {self.codex_bin!r}")
        (workdir / "prompt.txt").write_text(prompt, encoding="utf-8")
        (workdir / "checklist.txt").write_text("\n".join(checklist), encoding="utf-8")
        # Codex expects a repository; an empty one keeps it inside workdir.
        git = shutil.which("git")
        if git is not None:
            subprocess.run(  # noqa: S603  # nosec B603 - fixed argv
                [git, "init", "-q"], cwd=workdir, check=False, timeout=30
            )
        try:
            result = subprocess.run(  # noqa: S603  # nosec B603 - fixed argv
                [
                    binary,
                    "exec",
                    "--skip-git-repo-check",
                    "-s",
                    "workspace-write",
                    "-C",
                    str(workdir),
                    CODEX_INSTRUCTIONS,
                ],
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as err:
            _save_log(workdir, err.stdout, err.stderr)
            raise RuntimeError(
                f"Codex timed out after {self.timeout_seconds}s (log: {workdir})"
            ) from err
        _save_log(workdir, result.stdout, result.stderr)
        hero = workdir / "hero.png"
        if result.returncode != 0 or not hero.is_file():
            tail = (result.stderr or result.stdout or "").strip()[-300:]
            raise RuntimeError(
                f"Codex produced no image (exit {result.returncode}): {tail}"
            )
        review: dict[str, Any] = {}
        try:
            review = json.loads((workdir / "review.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning(
                "Codex wrote no readable review.json; treating as unreviewed"
            )
        return GeneratedImage(
            content=hero.read_bytes(),
            filename="hero.png",
            passed_review=bool(review.get("passed")),
            issues=[str(i) for i in review.get("issues") or []],
        )


class ImageAutoGenerator:
    """Scans parked publications and fills in their missing hero images."""

    def __init__(
        self,
        *,
        store: Any,
        checkpoints: Any,
        tool: ImageTool,
        provider_factory: Callable[[], Any],
        state_dir: Path,
        max_attempts: int = 2,
    ):
        self.store = store
        self.checkpoints = checkpoints
        self.tool = tool
        self.provider_factory = provider_factory
        self.state_dir = Path(state_dir)
        self.max_attempts = max_attempts

    # -- attempt ledger -----------------------------------------------------
    def _state_path(self, slug: str) -> Path:
        return self.state_dir / f"{self.store.brief_path(slug).stem}.json"

    def attempts(self, slug: str) -> int:
        try:
            data = json.loads(self._state_path(slug).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        return int(data.get("attempts", 0))

    def _record(self, slug: str, *, error: str | None) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "attempts": self.attempts(slug) + 1,
            "last_error": error,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._state_path(slug).write_text(json.dumps(payload), encoding="utf-8")

    # -- work ----------------------------------------------------------------
    def pending(self) -> list[Any]:
        """Waiting checkpoints whose brief is not ready and still has attempts."""
        found = []
        for run_id, _ in self.checkpoints.waiting():
            for cp in self.checkpoints.all(run_id).values():
                if cp.status != "waiting_for_image" or not cp.image_brief_slug:
                    continue
                if self.store.ready_for_article(cp.article_id, cp.image_brief_slug):
                    continue
                if self.attempts(cp.image_brief_slug) >= self.max_attempts:
                    continue
                found.append(cp)
        return found

    def run_once(self) -> int:
        """Generate at most one image; return how many were registered."""
        for cp in self.pending():
            slug = cp.image_brief_slug
            try:
                self.generate_for(cp)
            except Exception as err:  # noqa: BLE001 - one article never stops the queue
                logger.warning("Image autogen failed for {}: {}", slug, err)
                self._record(slug, error=str(err)[:500])
                continue
            self._record(slug, error=None)
            return 1
        return 0

    def generate_for(self, cp: Any) -> Any:
        brief = self.store.load_brief(cp.image_brief_slug)
        if brief is None or brief.article_id != str(cp.article_id):
            raise ValueError(f"No brief {cp.image_brief_slug!r} for this article")
        direction = direct_art(
            self.provider_factory(), dict(cp.draft.frontmatter), cp.draft.content
        )
        prompt = render_prompt(direction)
        # Codex works outside /tmp, in a folder kept only when it fails so the
        # log can be inspected (see the attempt ledger's last_error).
        work_root = self.state_dir / "work"
        work_root.mkdir(parents=True, exist_ok=True)
        workdir = Path(tempfile.mkdtemp(prefix=f"{brief.slug}-", dir=work_root))
        image = self.tool.generate(prompt, checklist_for(direction), workdir)
        shutil.rmtree(workdir, ignore_errors=True)
        width, height = validate_hero(image.content)
        if not image.passed_review:
            logger.warning(
                "Generated image for {} kept with review issues: {}",
                brief.slug,
                image.issues,
            )
        return self.store.stage_upload(
            brief=brief,
            filename=image.filename,
            content=image.content,
            draft_alt_text=direction.alt_text_es,
            topic=brief.topic,
            news_angle=brief.news_angle,
            scientific_domain=brief.scientific_domain,
            subject_scene=direction.focal_subject,
            image_origin="ai_generated",
            generation_metadata=ImageGenerationMetadata(
                prompt=prompt,
                tool=TOOL_NAME,
                sha256=hashlib.sha256(image.content).hexdigest(),
                width=width,
                height=height,
            ),
            generated_prompt=prompt,
            prompt_version=IMAGE_PROMPT_V2_VERSION,
        )


def start_autogen_thread(
    generator: ImageAutoGenerator, stop: threading.Event, interval_seconds: int
) -> threading.Thread:
    """Background loop owned by the serving process; ``stop`` ends it."""

    def loop() -> None:
        while not stop.is_set():
            try:
                generator.run_once()
            except Exception:  # noqa: BLE001 - keep the loop alive
                logger.exception("Image autogen scan failed")
            stop.wait(interval_seconds)

    thread = threading.Thread(target=loop, name="image-autogen", daemon=True)
    thread.start()
    return thread
