"""Deterministic end-to-end harness from replay collector to frontend handoff."""

from __future__ import annotations

import asyncio
import errno
import json
import os
import shutil
import stat
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import mkdtemp
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterable, List, Mapping
from unittest.mock import patch

import git
from news_collector.config import ALL_SOURCES
from news_collector.config.settings import get_runtime_config
from news_collector.contracts import (
    MANIFEST_FILENAME,
    SCHEMA_VERSION,
    PipelineE2ERunSummary,
    PipelineStageSnapshot,
)
from news_collector.logic.workflows.refinery_engine import RefineryEngine
from news_collector.perf.load_replay import CollectorReplaySession, ReplayEvent
from news_collector.scoring.feature_scorer import FeatureBasedScorer
from news_collector.storage.database import DatabaseManager
from news_collector.system import create_system
from news_collector.utils.slug import slugify


def _ignore_special_files(directory: str, names: list[str]) -> set[str]:
    """Excluye sockets, FIFOs y archivos de dispositivo del árbol fuente.

    `shutil.copy2` no puede copiar archivos especiales (no son datos), así
    que un socket Unix vivo (p. ej. el daemon de una herramienta) o una
    FIFO en el árbol fuente haría fallar `copytree` entero. Se detectan con
    `os.lstat`; si el archivo desaparece entre el listado y el stat, se
    ignora igualmente (no se propaga el error). Los enlaces simbólicos NO
    se excluyen: `copytree` los maneja bien y el repo frontend real
    contiene symlinks (p. ej. `node_modules/.bin/*`).
    """
    ignored: set[str] = set()
    for name in names:
        try:
            mode = os.lstat(os.path.join(directory, name)).st_mode
        except OSError:
            ignored.add(name)
            continue
        if (
            stat.S_ISSOCK(mode)
            or stat.S_ISFIFO(mode)
            or stat.S_ISBLK(mode)
            or stat.S_ISCHR(mode)
        ):
            ignored.add(name)
    return ignored


def _combined_copy_ignore(
    *ignore_callables: Callable[[str, list[str]], set[str]],
) -> Callable[[str, list[str]], set[str]]:
    """Combina varios callables `ignore` de copytree en uno solo."""

    def _combined(directory: str, names: list[str]) -> set[str]:
        excluded: set[str] = set()
        for ignore in ignore_callables:
            excluded |= ignore(directory, names)
        return excluded

    return _combined


FRONTEND_COPY_IGNORE = _combined_copy_ignore(
    shutil.ignore_patterns(".git", "node_modules", "dist", ".astro"),
    _ignore_special_files,
)
NODE_MODULES_COPY_IGNORE = _combined_copy_ignore(
    shutil.ignore_patterns(".cache"),
    _ignore_special_files,
)


def _slugify(value: str) -> str:
    return slugify(value)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_frontend_root() -> Path | None:
    explicit = os.environ.get("NOTICIENCIAS_FRONTEND_ROOT")
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if (candidate / "package.json").exists():
            return candidate

    candidate = (_repo_root().parent / "noticiencias").resolve()
    if (candidate / "package.json").exists():
        return candidate
    return None


def _article_to_dicts(items: Iterable[Any]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for item in items:
        if hasattr(item, "to_dict"):
            payload = dict(item.to_dict())
            if hasattr(item, "article_metadata"):
                payload["article_metadata"] = item.article_metadata
            if hasattr(item, "processing_status"):
                payload["processing_status"] = item.processing_status
            if hasattr(item, "error_message"):
                payload["error_message"] = item.error_message
            if hasattr(item, "content"):
                payload["content"] = item.content
            result.append(payload)
        else:
            result.append(dict(item))
    return result


def _load_fixture(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"E2E fixture must be a JSON object: {path}")
    return payload


def _parse_published(value: str) -> datetime | None:
    """Parse an article fixture ``published`` timestamp into an aware UTC datetime."""
    normalized = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _relative_fixture_dates(fixture: Mapping[str, Any]) -> dict[str, Any]:
    """Shift hardcoded ``published`` timestamps to be relative to "now".

    E2E fixtures were authored with absolute publish dates. Scoring enforces
    ``candidate_max_age_days`` and a recency curve that reaches 0.0 at the
    cutoff, so stale fixture timestamps would age out of the candidate pool
    over time and the scenarios would flip their expected outcome. Shift every
    article's ``published`` value so the newest one lands ~2h before now,
    preserving the original relative gaps between articles.
    """
    payload = dict(fixture)
    raw_events = payload.get("replay_events", [])
    if not isinstance(raw_events, list):
        return payload
    events = [dict(item) for item in raw_events]

    newest = _newest_published(events)
    if newest is None:
        return payload

    offset = datetime.now(timezone.utc) - timedelta(hours=2) - newest

    for event in events:
        for article in event.get("articles", []):
            published = article.get("published")
            if not published:
                continue
            dt = _parse_published(published)
            if dt is None:
                continue
            article["published"] = (dt + offset).astimezone(timezone.utc).isoformat()

    payload["replay_events"] = events
    return payload


def _newest_published(events: list[dict[str, Any]]) -> datetime | None:
    """Return the newest valid ``published`` timestamp across all replay events."""
    newest: datetime | None = None
    for event in events:
        for article in event.get("articles", []):
            published = article.get("published")
            if not published:
                continue
            dt = _parse_published(published)
            if dt is None:
                continue
            if newest is None or dt > newest:
                newest = dt
    return newest


def _build_replay_session(fixture: Mapping[str, Any]) -> CollectorReplaySession:
    fixture = _relative_fixture_dates(fixture)
    events_payload = fixture.get("replay_events", [])
    events = [ReplayEvent.from_mapping(dict(item)) for item in events_payload]
    return CollectorReplaySession(events)


def _build_source_config(
    fixture: Mapping[str, Any], replay_session: CollectorReplaySession
) -> tuple[str, Dict[str, Any]]:
    source_id = str(fixture["source_id"])
    source_map = replay_session.build_source_config()
    source_config = dict(source_map[source_id])
    source_config.update(dict(fixture.get("source_config", {})))
    source_config.setdefault("collector_type", "rss")
    source_config.setdefault("content_mode", "summary_only")
    source_config.setdefault("enrichment_strategy", "none")
    source_config.setdefault("headless_enabled", False)
    return source_id, source_config


class LocalEditorialEditor:
    """Deterministic editor seam for E2E publication runs."""

    def __init__(self, mode: str = "valid", forced_permalink: str | None = None):
        self.mode = mode
        self.forced_permalink = forced_permalink
        self.critic_threshold = None

    def process_article(
        self,
        article: Mapping[str, Any],
        *,
        override_date: str,
        explicit_article_id: str,
    ) -> str:
        slug = _slugify(str(article.get("title") or explicit_article_id))
        permalink = self.forced_permalink or f"/{slug}/"
        categories = ["Ciencia"]
        tags = ["ciencia", "latam"]
        source_url = str(article.get("url") or "https://example.com/source")
        source_name = str(article.get("source_name") or "Unknown Source")
        body_lines = [
            "Articulo generado por el harness e2e.",
            str(article.get("summary") or ""),
            str(article.get("content") or ""),
        ]

        if self.mode == "invalid_taxonomy":
            tags = ["TagInvalido!"]
            categories = ["InvalidCategory"]

        return "\n".join(
            [
                "---",
                f"title: {str(article.get('title') or explicit_article_id)!r}",
                f"schema_version: {SCHEMA_VERSION}",
                f"excerpt: {str(article.get('summary') or '')[:180]!r}",
                "author: 'Noticiencias'",
                f"date: {override_date}",
                f"categories: [{', '.join(repr(item) for item in categories)}]",
                f"tags: [{', '.join(repr(item) for item in tags)}]",
                f"image: {str(article.get('image_url') or 'https://example.com/image.jpg')!r}",
                f"image_alt: {str(article.get('image_alt') or 'Imagen editorial')!r}",
                f"permalink: {permalink!r}",
                f"source_url: {source_url!r}",
                f"refinery_id: {str(article.get('id') or explicit_article_id)!r}",
                "translation_method: 'pipeline_e2e'",
                "review_status: 'approved'",
                "confidence: 'alta'",
                "investigation: false",
                "featured: false",
                f"slug: {slug!r}",
                "sources:",
                f"  - title: {str(article.get('title') or explicit_article_id)!r}",
                f"    url: {source_url!r}",
                f"    publisher: {source_name!r}",
                "---",
                "",
                *body_lines,
                "",
            ]
        )


class LocalPRGitHandler:
    """Local Git seam that simulates branch, commit, and PR creation."""

    def create_branch(
        self,
        repo_obj: git.Repo,
        *,
        branch_prefix: str,
        explicit_name: str,
    ) -> str:
        branch_name = f"{branch_prefix}-{explicit_name}"
        repo_obj.git.checkout("-B", branch_name)
        return branch_name

    def commit_and_push(
        self, repo_obj: git.Repo, message: str, branch_name: str
    ) -> None:
        repo_obj.git.add(A=True)
        if repo_obj.is_dirty(untracked_files=True):
            repo_obj.index.commit(message)

    def create_pull_request(
        self,
        *,
        repo_url: str,
        branch_name: str,
        title: str,
        body: str,
    ) -> str:
        del repo_url, title, body
        return f"https://example.test/pr/{branch_name}"


def _fixture_check_script() -> str:
    return """\
const fs = require("fs");
const path = require("path");

const mode = process.argv[2];
const postsDir = path.join(process.cwd(), "src", "content", "posts");
const manifestPath = path.join(postsDir, "refinery_manifest.json");

function fail(message) {
  console.error(message);
  process.exit(1);
}

function parseFrontmatter(text) {
  const match = text.match(/^---\\n([\\s\\S]*?)\\n---/);
  if (!match) return {};
  const result = {};
  for (const line of match[1].split("\\n")) {
    const idx = line.indexOf(":");
    if (idx === -1) continue;
    const key = line.slice(0, idx).trim();
    const value = line.slice(idx + 1).trim();
    result[key] = value;
  }
  return result;
}

function loadPosts() {
  const files = fs.existsSync(postsDir)
    ? fs.readdirSync(postsDir).filter((name) => name.endsWith(".md"))
    : [];
  return files.map((file) => {
    const fullPath = path.join(postsDir, file);
    const text = fs.readFileSync(fullPath, "utf8");
    return { file, text, frontmatter: parseFrontmatter(text) };
  });
}

function loadManifest() {
  if (!fs.existsSync(manifestPath)) {
    fail("published content sidecar missing refinery_manifest");
  }
  const parsed = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    fail("published content sidecar malformed");
  }
  return parsed;
}

const posts = loadPosts();
const manifest = loadManifest();

if (mode === "lint") {
  console.log("lint ok");
  process.exit(0);
}

if (mode === "validate_content") {
  for (const post of posts) {
    if ((post.frontmatter["categories"] || "").includes("Invalid")) {
      fail("taxonomy contract violation: invalid categories");
    }
    if (!(post.frontmatter["permalink"] || "").length) {
      fail("schema mismatch: missing permalink");
    }
  }
  console.log("validate ok");
  process.exit(0);
}

if (mode === "build") {
  for (const post of posts) {
    if (post.text.includes("BUILD_FAIL")) {
      fail("route generation exploded");
    }
  }
  console.log("build ok");
  process.exit(0);
}

if (mode === "test_dist") {
  const seen = new Map();
  for (const post of posts) {
    const permalink = post.frontmatter["permalink"] || "";
    if (seen.has(permalink)) {
      fail("duplicate permalink detected");
    }
    seen.set(permalink, post.file);
  }
  for (const [id, file] of Object.entries(manifest)) {
    if (!fs.existsSync(path.join(postsDir, file))) {
      fail(`published content sidecar missing entry for ${id}`);
    }
  }
  console.log("dist ok");
  process.exit(0);
}

if (mode === "test_audit") {
  for (const post of posts) {
    if (post.text.includes("AUDIT_FAIL")) {
      fail("audit regression detected");
    }
  }
  console.log("audit ok");
  process.exit(0);
}

fail(`unknown mode: ${mode}`);
"""


def _init_local_repo(target_dir: Path) -> git.Repo:
    repo = git.Repo.init(target_dir)
    with repo.config_writer() as config_writer:
        config_writer.set_value("user", "name", "E2E Harness")
        config_writer.set_value("user", "email", "e2e@example.test")
    repo.git.add(A=True)
    if repo.is_dirty(untracked_files=True):
        repo.index.commit("Initial fixture frontend repo")
    return repo


def _normalize_real_frontend_baseline(target_dir: Path) -> None:
    footer_path = (
        target_dir / "src" / "components" / "template" / "widgets" / "Footer.astro"
    )
    if not footer_path.exists():
        return
    npx_path = shutil.which("npx")
    if npx_path is None:
        return
    subprocess.run(  # noqa: S603
        [npx_path, "prettier", "--write", str(footer_path.relative_to(target_dir))],
        cwd=str(target_dir),
        text=True,
        capture_output=True,
        check=False,
    )


def _copy_with_link_fallback(src: str, dst: str) -> None:
    try:
        os.link(src, dst)
    except OSError as exc:
        if exc.errno not in {errno.EMLINK, errno.EXDEV, errno.EPERM, errno.EACCES}:
            raise
        shutil.copy2(src, dst)


def _write_frontend_fixture_repo(target_dir: Path, scenario: Mapping[str, Any]) -> Path:
    posts_dir = target_dir / "src" / "content" / "posts"
    scripts_dir = target_dir / "scripts"
    posts_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "node_modules").mkdir(parents=True, exist_ok=True)

    package_json = {
        "name": "noticiencias-e2e-fixture",
        "version": "1.0.0",
        "private": True,
        "scripts": {
            "lint": "node scripts/check.js lint",
            "validate:content": "node scripts/check.js validate_content",
            "build": "node scripts/check.js build",
            "test:dist": "node scripts/check.js test_dist",
            "test:audit": "node scripts/check.js test_audit",
            "publish:image-derivatives": "echo 'mock: image derivatives ok'",
        },
    }
    _write_json(target_dir / "package.json", package_json)
    (scripts_dir / "check.js").write_text(_fixture_check_script(), encoding="utf-8")

    manifest: Dict[str, str] = {}
    for item in scenario.get("frontend_fixture", {}).get("preexisting_posts", []):
        filename = str(item["filename"])
        manifest[str(item["refinery_id"])] = filename
        (posts_dir / filename).write_text(str(item["content"]), encoding="utf-8")

    _write_json(posts_dir / MANIFEST_FILENAME, manifest)
    _init_local_repo(target_dir)
    return target_dir


def _prepare_target_repo(
    bundle_dir: Path, scenario: Mapping[str, Any]
) -> tuple[Path, git.Repo]:
    target_dir = bundle_dir / "target_repo"
    template_root = scenario.get("frontend_root")
    if not template_root:
        template_root = _default_frontend_root()
    if template_root:
        source_root = Path(str(template_root)).resolve()
        shutil.copytree(source_root, target_dir, ignore=FRONTEND_COPY_IGNORE)
        source_node_modules = source_root / "node_modules"
        if source_node_modules.exists():
            shutil.copytree(
                source_node_modules,
                target_dir / "node_modules",
                copy_function=_copy_with_link_fallback,
                ignore=NODE_MODULES_COPY_IGNORE,
            )
        _normalize_real_frontend_baseline(target_dir)
        repo = _init_local_repo(target_dir)
    else:
        _write_frontend_fixture_repo(target_dir, scenario)
        repo = git.Repo(target_dir)
    return target_dir, repo


def _make_engine_config(bundle_dir: Path) -> Any:
    return SimpleNamespace(
        app=SimpleNamespace(
            policy_integrity_mode="disabled",
            editorial_mode="standard",
        ),
        paths=SimpleNamespace(data_dir=str(bundle_dir / "runtime_data")),
        github=SimpleNamespace(target_repo_url="https://example.test/noticiencias"),
    )


def _build_db_snapshot(db: DatabaseManager) -> Dict[str, Any]:
    return {
        "pending": _article_to_dicts(db.get_pending_articles()),
        "validated": _article_to_dicts(db.get_pending_articles(status="validated")),
        "rejected": _article_to_dicts(db.get_pending_articles(status="rejected")),
        "completed": _article_to_dicts(db.get_articles_by_score(limit=50, min_score=0)),
    }


def _record_stage(
    stages: list[PipelineStageSnapshot],
    *,
    stage: str,
    success: bool,
    details: Dict[str, Any],
    artifact_path: Path | None = None,
    failure_class: str | None = None,
) -> None:
    stages.append(
        PipelineStageSnapshot(
            stage=stage,  # type: ignore[arg-type]
            success=success,
            details=details,
            artifact_path=str(artifact_path) if artifact_path else None,
            failure_class=failure_class,
        )
    )


def _first_failed_stage(stages: list[PipelineStageSnapshot]) -> str | None:
    for stage in stages:
        if not stage.success:
            return stage.stage
    return None


def _root_failure_stage(stages: list[PipelineStageSnapshot]) -> str | None:
    for stage in stages:
        if (
            stage.stage == "frontend_validation"
            and not stage.success
            and not stage.details.get("skipped")
        ):
            return stage.stage
    return _first_failed_stage(stages)


def run_pipeline_e2e_scenario(  # noqa: C901
    fixture_path: str | Path,
    *,
    bundle_root: str | Path | None = None,
) -> PipelineE2ERunSummary:
    fixture_file = Path(fixture_path).resolve()
    fixture = _load_fixture(fixture_file)
    scenario_name = str(fixture.get("scenario", fixture_file.stem))

    if bundle_root is None:
        bundle_dir = Path(mkdtemp(prefix=f"pipeline-e2e-{scenario_name}-"))
    else:
        bundle_dir = Path(bundle_root).resolve()
        if bundle_dir.exists():
            shutil.rmtree(bundle_dir)
        bundle_dir.mkdir(parents=True, exist_ok=True)

    stages: list[PipelineStageSnapshot] = []
    frontend_validation_summary_path: str | None = None
    publication_attempt_summary_path: str | None = None
    selected_article_id: str | None = None
    expected_article_id = fixture.get("expected", {}).get("selected_article_id")
    first_divergence: str | None = None

    try:
        input_artifact = _write_json(bundle_dir / "input" / fixture_file.name, fixture)
        replay_session = _build_replay_session(fixture)
        source_id, source_config = _build_source_config(fixture, replay_session)
        db_path = bundle_dir / "runtime" / "e2e.db"
        db = DatabaseManager({"type": "sqlite", "path": db_path})

        with (
            patch("news_collector.system.bootstrap.build_database", return_value=db),
            patch(
                "news_collector.storage.database.get_database_manager", return_value=db
            ),
            patch(
                "news_collector.collectors.base_collector.get_database_manager",
                return_value=db,
            ),
        ):
            previous_smoke = os.environ.get("NOTICIENCIAS_SMOKE")
            os.environ["NOTICIENCIAS_SMOKE"] = "1"
            system = None
            try:
                system = create_system()
                if not system.initialize():
                    raise RuntimeError("System initialization failed for E2E harness")
                system.scorer = FeatureBasedScorer(get_runtime_config().scoring_config)
                ALL_SOURCES[source_id] = source_config
                rss = system.collector.collectors["rss"]

                with replay_session.patch_collector(rss):
                    report = asyncio.run(
                        system.run_collection_cycle(
                            sources_filter=[source_id],
                            dry_run=False,
                            trace_id=f"e2e-{scenario_name}",
                        )
                    )
            finally:
                ALL_SOURCES.pop(source_id, None)
                if previous_smoke is None:
                    os.environ.pop("NOTICIENCIAS_SMOKE", None)
                else:
                    os.environ["NOTICIENCIAS_SMOKE"] = previous_smoke
                if system is not None:
                    asyncio.run(system.shutdown())

        collection_artifact = _write_json(
            bundle_dir / "artifacts" / "collection_report.json", report
        )
        collection_summary = dict(report.get("summary", {}))
        _record_stage(
            stages,
            stage="collection",
            success=collection_summary.get("sources_processed", 0) > 0,
            details=collection_summary,
            artifact_path=collection_artifact,
        )

        active_db = DatabaseManager({"type": "sqlite", "path": db_path})

        db_snapshot = _build_db_snapshot(active_db)
        validation_artifact = _write_json(
            bundle_dir / "artifacts" / "db_snapshot.json", db_snapshot
        )
        total_persisted_candidates = (
            len(db_snapshot["pending"])
            + len(db_snapshot["validated"])
            + len(db_snapshot["rejected"])
            + len(db_snapshot["completed"])
        )
        validation_success = total_persisted_candidates > 0
        _record_stage(
            stages,
            stage="validation",
            success=validation_success,
            details={
                "pending_count": len(db_snapshot["pending"]),
                "validated_count": len(db_snapshot["validated"]),
                "rejected_count": len(db_snapshot["rejected"]),
                "completed_count": len(db_snapshot["completed"]),
                "total_persisted_candidates": total_persisted_candidates,
            },
            artifact_path=validation_artifact,
            failure_class="no_persisted_candidates" if not validation_success else None,
        )

        scoring_artifact = _write_json(
            bundle_dir / "artifacts" / "scoring_selection.json",
            {
                "scoring_results": report.get("scoring_results", {}),
                "selection_results": report.get("selection_results", {}),
            },
        )
        _record_stage(
            stages,
            stage="scoring",
            success="scoring_results" in report,
            details=dict(report.get("scoring_results", {}).get("statistics", {})),
            artifact_path=scoring_artifact,
            failure_class=None if "scoring_results" in report else "scoring_missing",
        )

        export_path = bundle_dir / "artifacts" / "latest_articles.json"
        with (
            patch(
                "news_collector.system.bootstrap.build_database", return_value=active_db
            ),
            patch(
                "news_collector.storage.database.get_database_manager",
                return_value=active_db,
            ),
            patch(
                "news_collector.collectors.base_collector.get_database_manager",
                return_value=active_db,
            ),
        ):
            previous_smoke = os.environ.get("NOTICIENCIAS_SMOKE")
            os.environ["NOTICIENCIAS_SMOKE"] = "1"
            system = None
            try:
                system = create_system()
                if not system.initialize():
                    raise RuntimeError("System initialization failed for export phase")
                export_payload = system.export_latest_articles(
                    file_path=str(export_path), limit=10
                )
            finally:
                if previous_smoke is None:
                    os.environ.pop("NOTICIENCIAS_SMOKE", None)
                else:
                    os.environ["NOTICIENCIAS_SMOKE"] = previous_smoke
                if system is not None:
                    asyncio.run(system.shutdown())

        export_articles = list(export_payload.get("articles", []))
        _record_stage(
            stages,
            stage="export",
            success=export_path.exists(),
            details={
                "article_count": len(export_articles),
                "export_path": str(export_path),
            },
            artifact_path=export_path,
            failure_class=None if export_path.exists() else "export_missing",
        )

        approved_article = export_articles[0] if export_articles else None
        selection_artifact = _write_json(
            bundle_dir / "artifacts" / "approved_article.json",
            approved_article or {"approved": False},
        )
        selected_article_id = (
            str(approved_article.get("id"))
            if isinstance(approved_article, dict)
            else None
        )
        selected_article_url = (
            str(approved_article.get("url"))
            if isinstance(approved_article, dict)
            else None
        )
        expected_selected_url = fixture.get("expected", {}).get("selected_article_url")
        approval_success = approved_article is not None
        selection_failure_class: str | None = None
        if approved_article is None:
            selection_failure_class = "no_publishable_candidates"
            first_divergence = "selection_empty"
        elif expected_selected_url and selected_article_url != expected_selected_url:
            approval_success = False
            selection_failure_class = "selection_mismatch"
            first_divergence = f"selection_mismatch actual={selected_article_url} expected={expected_selected_url}"
        _record_stage(
            stages,
            stage="selection",
            success=approval_success,
            details={
                "selected_article_id": selected_article_id,
                "selected_article_url": selected_article_url,
                "expected_selected_url": expected_selected_url,
            },
            artifact_path=selection_artifact,
            failure_class=selection_failure_class,
        )
        _record_stage(
            stages,
            stage="approval",
            success=approved_article is not None,
            details={"approved_article_id": selected_article_id},
            artifact_path=selection_artifact,
            failure_class=(
                "no_publishable_candidates" if approved_article is None else None
            ),
        )

        publication_db = DatabaseManager({"type": "sqlite", "path": db_path})
        generated_post_artifact = bundle_dir / "artifacts" / "generated_post.md"

        if approved_article is not None:
            if not approved_article.get("image_url"):
                approved_article["image_url"] = (
                    "https://example.test/e2e-placeholder.png"
                )
            if not approved_article.get("image_alt"):
                approved_article["image_alt"] = "Imagen e2e"
            target_dir, repo = _prepare_target_repo(bundle_dir, fixture)
            editor_mode = str(
                fixture.get("publication", {}).get("editor_mode", "valid")
            )
            forced_permalink = fixture.get("publication", {}).get("forced_permalink")
            engine = RefineryEngine(
                db_manager=publication_db,
                git_handler=LocalPRGitHandler(),
                editor_agent=LocalEditorialEditor(
                    mode=editor_mode,
                    forced_permalink=(
                        str(forced_permalink) if forced_permalink else None
                    ),
                ),
                config=_make_engine_config(bundle_dir),
            )
            engine._download_image = lambda url, slug, target: url

            if fixture.get("publication", {}).get("seed_publishing_state"):
                publication_db.mark_article_publishing(
                    int(selected_article_id),
                    str(
                        fixture.get("publication", {}).get(
                            "publishing_branch",
                            "content/update-stuck-publishing-recovery",
                        )
                    ),
                )

            publication_result = engine.process_articles(
                [approved_article], repo, target_dir
            )
            attempt_name = engine._safe_publication_artifact_name(
                str(selected_article_id)
            )
            publication_attempt_path = (
                engine.publication_attempts_dir / f"{attempt_name}.json"
            )
            if publication_attempt_path.exists():
                publication_attempt_summary_path = str(publication_attempt_path)
            publication_success = publication_result.get("processed_count", 0) == 1
            publication_details = dict(publication_result)
            if publication_attempt_path.exists():
                publication_details["attempt_summary"] = json.loads(
                    publication_attempt_path.read_text(encoding="utf-8")
                )
                frontend_validation_summary_path = publication_details[
                    "attempt_summary"
                ].get("validation_summary_path")
                output_filename = publication_details["attempt_summary"].get(
                    "output_filename"
                )
                if output_filename:
                    generated_post_path = (
                        target_dir / "src" / "content" / "posts" / str(output_filename)
                    )
                    if generated_post_path.exists():
                        generated_post_artifact.write_text(
                            generated_post_path.read_text(encoding="utf-8"),
                            encoding="utf-8",
                        )
                        publication_details["generated_post_path"] = str(
                            generated_post_artifact
                        )
            if not publication_success and not first_divergence:
                errors = publication_details.get("errors", [])
                if errors:
                    first_divergence = str(errors[0].get("error") or errors[0])
            _record_stage(
                stages,
                stage="publication",
                success=publication_success,
                details=publication_details,
                artifact_path=(
                    generated_post_artifact
                    if generated_post_artifact.exists()
                    else (
                        publication_attempt_path
                        if publication_attempt_path.exists()
                        else None
                    )
                ),
                failure_class=publication_details.get("attempt_summary", {}).get(
                    "failure_class"
                ),
            )

            if frontend_validation_summary_path:
                frontend_payload = json.loads(
                    Path(frontend_validation_summary_path).read_text(encoding="utf-8")
                )
                _record_stage(
                    stages,
                    stage="frontend_validation",
                    success=bool(frontend_payload.get("success")),
                    details=frontend_payload,
                    artifact_path=Path(frontend_validation_summary_path),
                    failure_class=frontend_payload.get("overall_failure_class"),
                )
            else:
                _record_stage(
                    stages,
                    stage="frontend_validation",
                    success=True,
                    details={"skipped": True},
                )
        else:
            _record_stage(
                stages,
                stage="publication",
                success=True,
                details={"skipped": True, "reason": "no_approved_article"},
            )
            _record_stage(
                stages,
                stage="frontend_validation",
                success=True,
                details={"skipped": True, "reason": "no_approved_article"},
            )

        root_failure_stage = _root_failure_stage(stages)
        summary = PipelineE2ERunSummary(
            scenario=scenario_name,
            generated_at=_now_iso(),
            fixture_path=str(input_artifact),
            success=root_failure_stage is None,
            diagnostics_bundle_dir=str(bundle_dir),
            selected_article_id=selected_article_id,
            expected_article_id=(
                str(expected_article_id) if expected_article_id is not None else None
            ),
            root_failure_stage=root_failure_stage,  # type: ignore[arg-type]
            first_divergence=first_divergence,
            publication_attempt_summary_path=publication_attempt_summary_path,
            frontend_validation_summary_path=frontend_validation_summary_path,
            stages=stages,
        )
        _write_json(bundle_dir / "run_summary.json", summary.model_dump(mode="json"))
        return summary
    finally:
        pass
