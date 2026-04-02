from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import git
import yaml
from news_collector.components.publishing import GitHubPublisher

POSTS_SUBPATH = Path("src/content/posts")


@dataclass(frozen=True)
class PublishedArticleRecord:
    file_path: Path
    file_name: str
    title: str
    refinery_id: str | None
    frontmatter: dict[str, Any]
    modified_at: datetime


@dataclass(frozen=True)
class PublishedContentSnapshot:
    repo_root: Path
    posts_dir: Path
    articles: list[PublishedArticleRecord]
    source_label: str
    freshness_label: str


def normalize_repo_url(repo_url: str) -> str:
    value = str(repo_url or "").strip()
    if not value:
        return ""

    if value.startswith("git@"):
        _, _, remainder = value.partition(":")
        host = value.split("@", 1)[1].split(":", 1)[0].lower()
        path = remainder.removesuffix(".git").strip("/")
        return f"{host}/{path}".lower()

    parsed = urlparse(value)
    host = parsed.hostname or ""
    path = parsed.path.removesuffix(".git").strip("/")
    if not host and "github.com/" in value:
        _, _, remainder = value.partition("github.com/")
        host = "github.com"
        path = remainder.removesuffix(".git").strip("/")

    if not host or not path:
        return value.removesuffix(".git").rstrip("/").lower()

    return f"{host.lower()}/{path.lower()}"


def repo_matches_target(repo_path: Path, target_repo_url: str) -> bool:
    repo_git_dir = repo_path / ".git"
    if not repo_git_dir.exists():
        return False

    try:
        repo = git.Repo(repo_path)
        origin_url = next(repo.remote("origin").urls)
    except Exception:
        return False

    return normalize_repo_url(origin_url) == normalize_repo_url(target_repo_url)


def iter_candidate_repo_roots(
    collector_repo_root: Path,
    *,
    extra_candidates: Iterable[Path] | None = None,
) -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()

    def add_candidate(path: Path) -> None:
        resolved = path.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        candidates.append(resolved)

    if extra_candidates:
        for candidate in extra_candidates:
            add_candidate(candidate)

    add_candidate(Path.cwd())

    for parent in Path.cwd().resolve().parents:
        if (parent / ".git").exists():
            add_candidate(parent)

    parent_dir = collector_repo_root.parent
    add_candidate(parent_dir)
    for child in parent_dir.iterdir():
        if child.is_dir():
            add_candidate(child)

    return candidates


def find_local_target_checkout(
    target_repo_url: str,
    *,
    collector_repo_root: Path,
    extra_candidates: Iterable[Path] | None = None,
) -> Path | None:
    for candidate in iter_candidate_repo_roots(
        collector_repo_root, extra_candidates=extra_candidates
    ):
        if repo_matches_target(candidate, target_repo_url):
            posts_dir = candidate / POSTS_SUBPATH
            if posts_dir.exists():
                return candidate
    return None


def extract_frontmatter_block(text: str) -> str | None:
    if not text.startswith("---"):
        return None

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None

    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return "\n".join(lines[1:idx])
    return None


def parse_frontmatter_text(text: str) -> dict[str, Any]:
    frontmatter_block = extract_frontmatter_block(text)
    if not frontmatter_block:
        return {}

    parsed = yaml.safe_load(frontmatter_block)
    return parsed if isinstance(parsed, dict) else {}


def parse_frontmatter_file(file_path: Path) -> dict[str, Any]:
    return parse_frontmatter_text(file_path.read_text(encoding="utf-8"))


def read_published_article(file_path: Path) -> PublishedArticleRecord:
    frontmatter = parse_frontmatter_file(file_path)
    title = str(frontmatter.get("title") or file_path.name)
    refinery_id = frontmatter.get("refinery_id")
    normalized_refinery_id = None
    if refinery_id is not None and str(refinery_id).strip():
        normalized_refinery_id = str(refinery_id).strip()

    return PublishedArticleRecord(
        file_path=file_path,
        file_name=file_path.name,
        title=title,
        refinery_id=normalized_refinery_id,
        frontmatter=frontmatter,
        modified_at=datetime.fromtimestamp(file_path.stat().st_mtime),
    )


def load_published_articles(posts_dir: Path) -> list[PublishedArticleRecord]:
    articles = [read_published_article(path) for path in sorted(posts_dir.glob("*.md"))]
    return sorted(articles, key=lambda article: article.file_name, reverse=True)


def format_freshness_label(articles: list[PublishedArticleRecord]) -> str:
    if not articles:
        return "Sin artículos detectados"

    freshest = max(article.modified_at for article in articles)
    return f"Última actualización local: {freshest.strftime('%Y-%m-%d %H:%M')}"


def truncate_refinery_id(refinery_id: str | None, *, limit: int = 52) -> str | None:
    if refinery_id is None:
        return None

    compact = " ".join(refinery_id.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 1].rstrip()}…"


def refresh_published_target_clone(
    *,
    target_repo_url: str,
    target_dir: Path,
    github_token: str = "",
) -> tuple[Path, str]:
    publisher = GitHubPublisher(github_token)

    if target_dir.exists() and (target_dir / ".git").exists():
        try:
            repo = git.Repo(target_dir)
            repo.remotes.origin.pull()
            return target_dir, "Clon temporal actualizado desde origin"
        except Exception:
            publisher.clone_repo(target_repo_url, target_dir)
            return target_dir, "Clon temporal recreado desde origin"

    publisher.clone_repo(target_repo_url, target_dir)
    return target_dir, "Clon temporal inicializado desde origin"


def build_published_content_snapshot(
    *,
    repo_root: Path,
    source_label: str,
) -> PublishedContentSnapshot:
    posts_dir = repo_root / POSTS_SUBPATH
    articles = load_published_articles(posts_dir)
    return PublishedContentSnapshot(
        repo_root=repo_root,
        posts_dir=posts_dir,
        articles=articles,
        source_label=source_label,
        freshness_label=format_freshness_label(articles),
    )


def resolve_published_content_snapshot(
    *,
    target_repo_url: str,
    collector_repo_root: Path,
    temp_target_dir: Path,
    github_token: str = "",
    refresh_clone: bool = False,
    extra_candidates: Iterable[Path] | None = None,
) -> PublishedContentSnapshot:
    local_checkout = find_local_target_checkout(
        target_repo_url,
        collector_repo_root=collector_repo_root,
        extra_candidates=extra_candidates,
    )
    if local_checkout is not None:
        return build_published_content_snapshot(
            repo_root=local_checkout,
            source_label="Checkout local verificado del frontend",
        )

    if refresh_clone:
        repo_root, clone_label = refresh_published_target_clone(
            target_repo_url=target_repo_url,
            target_dir=temp_target_dir,
            github_token=github_token,
        )
        return build_published_content_snapshot(
            repo_root=repo_root,
            source_label=clone_label,
        )

    if (temp_target_dir / POSTS_SUBPATH).exists():
        return build_published_content_snapshot(
            repo_root=temp_target_dir,
            source_label="Clon temporal existente del frontend",
        )

    repo_root, clone_label = refresh_published_target_clone(
        target_repo_url=target_repo_url,
        target_dir=temp_target_dir,
        github_token=github_token,
    )
    return build_published_content_snapshot(
        repo_root=repo_root,
        source_label=clone_label,
    )


def find_published_article_by_refinery_id(
    posts_dir: Path, refinery_id: str
) -> PublishedArticleRecord | None:
    target_id = str(refinery_id).strip()
    for article in load_published_articles(posts_dir):
        if article.refinery_id == target_id:
            return article
    return None
