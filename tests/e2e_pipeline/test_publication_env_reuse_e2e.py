"""Plan 133 e2e: two consecutive publishes against a local fixture remote.

Proves, on a real (local) git remote and the real publication path, that:

- the first publish clones the frontend checkout and runs ``npm ci``;
- the second publish REUSES that checkout (``publication.target_repo.reused``
  with ``reused: true``) and skips ``npm ci`` while still running the full
  frontend gate (lint/validate/build/dist/audit);
- both publishes produce byte-identical identity (filename, slug, date) —
  the reuse never changes publication identity (LAW-B5);
- after a publish the checkout is clean and the dependency marker lives
  outside it.

The fixture frontend is fully offline: ``npm ci`` installs a zero-dependency
lock and its ``prepare`` script materialises ``node_modules/.bin/prettier``
(the "toolchain" the reuse must preserve), so no registry access is needed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import git
import pytest
import yaml

from news_collector.components.publishing.github_publisher import GitHubPublisher
from news_collector.logic.workflows.frontend_publication_validation import (
    FRONTEND_DEPENDENCY_MARKER_DIRNAME,
)
from news_collector.logic.workflows.pipeline_e2e import (
    LocalEditorialAuditor,
    LocalEditorialEditor,
    LocalPRGitHandler,
    _fixture_check_script,
)
from news_collector.logic.workflows.publication_attempts import artifact_name
from news_collector.logic.workflows.publication_pipeline import _provision_target_repo
from news_collector.logic.workflows.refinery_engine import RefineryEngine
from news_collector.storage.database import DatabaseManager

pytestmark = pytest.mark.timeout(300)

_PACKAGE_JSON = {
    "name": "noticiencias-e2e-fixture",
    "version": "1.0.0",
    "private": True,
    "scripts": {
        # Runs on `npm ci`: mirrors the install materialising the toolchain.
        "prepare": "node scripts/prepare.js",
        "lint": "node scripts/check.js lint",
        "validate:content": "node scripts/check.js validate_content",
        "build": "node scripts/check.js build",
        "test:dist": "node scripts/check.js test_dist",
        "test:audit": "node scripts/check.js test_audit",
        "publish:image-derivatives": "echo 'mock: image derivatives ok'",
    },
}
_PACKAGE_LOCK = {
    "name": "noticiencias-e2e-fixture",
    "version": "1.0.0",
    "lockfileVersion": 3,
    "requires": True,
    "packages": {"": {"name": "noticiencias-e2e-fixture", "version": "1.0.0"}},
}
_PREPARE_SCRIPT = """\
const fs = require("fs");
const path = require("path");

// Mirrors `npm ci` materialising the toolchain: the reuse path must keep
// this tree, and the dependency marker must then skip the re-install.
const binDir = path.join(process.cwd(), "node_modules", ".bin");
fs.mkdirSync(binDir, { recursive: true });
const prettier = path.join(binDir, "prettier");
fs.writeFileSync(prettier, "#!/bin/sh\\nexit 0\\n");
fs.chmodSync(prettier, 0o755);
"""

_ARTICLE_SEED = {
    "url": "https://example.test/article-133",
    "original_url": "https://example.test/article-133",
    "title": "El checkout del frontend se reutiliza entre publicaciones",
    "summary": (
        "Resumen sintético suficientemente largo para superar la validación "
        "editorial del motor de refinería en la prueba de reutilización del "
        "checkout del frontend entre dos publicaciones consecutivas."
    ),
    "content": (
        "Contenido sintético de la prueba e2e del plan 133. Describe el "
        "comportamiento esperado del pipeline de publicación cuando el "
        "checkout del frontend ya existe y sus dependencias siguen vigentes."
    ),
    "image_url": "https://example.test/hero-133.png",
    "image_alt": "Imagen sintética de la prueba de reutilización del checkout.",
    "source_id": "e2e-local",
    "source_name": "E2E Local",
    "category": "ciencia",
    "language": "es",
    "published_date": datetime(2026, 1, 2, tzinfo=timezone.utc),
}


def _commit_all(repo_dir: Path, message: str) -> None:
    repo = git.Repo.init(repo_dir, initial_branch="main")
    with repo.config_writer() as config_writer:
        config_writer.set_value("user", "name", "Plan 133 e2e")
        config_writer.set_value("user", "email", "e2e@example.test")
    repo.git.add(A=True)
    repo.index.commit(message)


def _write_fixture_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "frontend-remote"
    remote.mkdir(parents=True)
    (remote / ".gitignore").write_text(
        "node_modules/\ndist/\n.astro/\n", encoding="utf-8"
    )
    (remote / "package.json").write_text(
        f"{json.dumps(_PACKAGE_JSON, indent=2)}\n", encoding="utf-8"
    )
    (remote / "package-lock.json").write_text(
        f"{json.dumps(_PACKAGE_LOCK, indent=2)}\n", encoding="utf-8"
    )
    scripts = remote / "scripts"
    scripts.mkdir()
    (scripts / "check.js").write_text(_fixture_check_script(), encoding="utf-8")
    (scripts / "prepare.js").write_text(_PREPARE_SCRIPT, encoding="utf-8")
    posts = remote / "src" / "content" / "posts"
    posts.mkdir(parents=True)
    (posts / "refinery_manifest.json").write_text("{}\n", encoding="utf-8")
    _commit_all(remote, "Initial fixture frontend")
    return remote


def _make_engine_config(runtime_dir: Path) -> Any:
    return SimpleNamespace(
        app=SimpleNamespace(
            policy_integrity_mode="disabled",
            editorial_mode="standard",
        ),
        paths=SimpleNamespace(data_dir=str(runtime_dir)),
        github=SimpleNamespace(target_repo_url="https://example.test/noticiencias"),
    )


def _publish_once(
    *,
    remote: Path,
    target: Path,
    runtime_dir: Path,
    run_index: int,
) -> dict:
    repo, reused = _provision_target_repo(
        GitHubPublisher(base_branch="main"), str(remote), target
    )
    db = DatabaseManager(
        {"type": "sqlite", "path": runtime_dir / f"e2e-{run_index}.db"}
    )
    # The production DB owns the article row the publication gates lock the
    # canonical slug against; each run gets its own DB so the second publish
    # proves identity determinism from scratch, not DB memoisation.
    row = db.save_article(dict(_ARTICLE_SEED))
    assert row is not None, "fixture article row was not persisted"
    article = {**_ARTICLE_SEED, "id": str(row.id)}
    engine = RefineryEngine(
        db_manager=db,
        git_handler=LocalPRGitHandler(),
        editor_agent=LocalEditorialEditor(),
        config=_make_engine_config(runtime_dir),
        remote_image_hosts=frozenset({"example.test"}),
    )
    engine._download_image = lambda url, slug, target_dir: url
    engine.auditor = LocalEditorialAuditor()

    result = engine.process_articles([article], repo, target)

    attempt_path = (
        engine.publication_attempts_dir / f"{artifact_name(str(article['id']))}.json"
    )
    attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
    output_filename = attempt.get("output_filename")
    validation_path = attempt.get("validation_summary_path")
    validation = (
        json.loads(Path(str(validation_path)).read_text(encoding="utf-8"))
        if validation_path
        else {}
    )
    post_path = target / "src" / "content" / "posts" / str(output_filename)
    frontmatter = (
        yaml.safe_load(post_path.read_text(encoding="utf-8").split("---", 2)[1])
        if output_filename and post_path.exists()
        else {}
    )
    checkout = git.Repo(target)
    marker_dir = (
        engine.publication_attempts_dir.parent / FRONTEND_DEPENDENCY_MARKER_DIRNAME
    )
    checks = list(validation.get("checks", []))
    return {
        "reused": reused,
        "processed_count": result.get("processed_count"),
        "attempt": attempt,
        "output_filename": output_filename,
        "check_names": [check["name"] for check in checks],
        "stage_seconds": sum(
            float(check.get("duration_seconds") or 0.0) for check in checks
        ),
        "npm_ci_seconds": next(
            (
                float(check.get("duration_seconds") or 0.0)
                for check in checks
                if check["name"] == "npm_ci"
            ),
            None,
        ),
        "post_bytes": post_path.read_bytes() if post_path.exists() else b"",
        "frontmatter": frontmatter,
        "checkout_status": checkout.git.status("--porcelain").strip(),
        "marker_files": (
            sorted(marker_dir.glob("*.json")) if marker_dir.exists() else []
        ),
    }


def test_two_publishes_reuse_the_checkout_and_keep_identity(
    tmp_path: Path, monkeypatch
) -> None:
    remote = _write_fixture_remote(tmp_path)
    target = tmp_path / "target"
    runtime_dir = tmp_path / "runtime_data"
    events: list = []

    import news_collector.logic.workflows.publication_pipeline as pipeline

    original_info = pipeline.logger.info

    def _record(*args, **kwargs):
        events.append(args[0] if args else None)
        return original_info(*args, **kwargs)

    monkeypatch.setattr(pipeline.logger, "info", _record)

    first = _publish_once(
        remote=remote, target=target, runtime_dir=runtime_dir, run_index=1
    )
    second = _publish_once(
        remote=remote, target=target, runtime_dir=runtime_dir, run_index=2
    )

    # First publish: fresh clone, install runs.
    assert first["reused"] is False
    assert first["processed_count"] == 1
    assert "npm_ci" in first["check_names"]
    assert first["check_names"] == [
        "npm_ci",
        "publish_image_derivatives",
        "format_post",
        "format_repo",
        "lint",
        "validate_content",
        "build",
        "test_dist",
        "test_audit",
    ]

    # Second publish: same checkout reused, install skipped, gate intact.
    assert second["reused"] is True
    assert second["processed_count"] == 1
    assert "npm_ci" not in second["check_names"]
    assert second["check_names"] == [
        name for name in first["check_names"] if name != "npm_ci"
    ]

    reuse_events = [
        event
        for event in events
        if isinstance(event, dict)
        and event.get("event") == "publication.target_repo.reused"
    ]
    assert [event["reused"] for event in reuse_events] == [False, True]

    # Identity is byte-identical across the two publishes (LAW-B5).
    assert first["output_filename"]
    assert first["output_filename"] == second["output_filename"]
    assert first["post_bytes"] == second["post_bytes"]
    for field in ("slug", "date", "permalink", "refinery_id"):
        assert first["frontmatter"].get(field) == second["frontmatter"].get(field)

    # Clean checkout; the marker lives outside it.
    assert second["checkout_status"] == ""
    assert len(second["marker_files"]) == 1
    marker = second["marker_files"][0]
    assert target.resolve() not in marker.resolve().parents
    assert marker.name.startswith("npm_ci_")
    marker_payload = json.loads(marker.read_text(encoding="utf-8"))
    assert marker_payload["lock_sha256"]
    assert marker_payload["provenance"] == "installed"

    # The installed toolchain the reuse exists to keep survived both runs.
    assert (target / "node_modules" / ".bin" / "prettier").exists()

    # Evidence for the plan's execution record (not asserted: wall clocks are
    # load-sensitive; the structural proof is the npm_ci presence/absence).
    print(
        "plan133 frontend stage seconds:"
        f" first={first['stage_seconds']:.3f} (npm_ci={first['npm_ci_seconds']}),"
        f" second={second['stage_seconds']:.3f} (npm_ci={second['npm_ci_seconds']})"
    )
