from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import git
import requests
import yaml
from news_collector.components.publishing import GitHubPublisher
from news_collector.contracts import MANIFEST_FILENAME
from news_collector.contracts.frontend_publication import (
    FRONTEND_REQUIRED_PUBLICATION_WORKFLOWS,
)
from news_collector.utils.slug import slugify

logger = logging.getLogger(__name__)

POSTS_SUBPATH = Path("src/content/posts")
HERO_PLACEHOLDER_ALLOWLIST_SUBPATH = Path("data/hero-image-placeholder-allowlist.json")
DELETED_ROUTE_SMOKE_CHECKS_SUBPATH = Path("data/deleted-route-smoke-checks.json")
DEFAULT_HERO_IMAGE = "~/assets/images/default.png"


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


@dataclass(frozen=True)
class DeployHealthStatus:
    branch: str
    current_repo_sha: str | None
    latest_run_sha: str | None
    latest_run_conclusion: str | None
    latest_run_url: str | None
    latest_successful_sha: str | None
    latest_successful_url: str | None
    is_live_stale: bool


@dataclass(frozen=True)
class FrontendPrCheckStatus:
    pr_url: str
    pr_number: int
    head_sha: str | None
    branch: str | None
    state: str | None
    mergeable_state: str | None
    required_workflows: tuple[str, ...]
    workflow_conclusions: dict[str, str | None]
    is_publish_ready: bool


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


def get_post_image_source(frontmatter: dict[str, Any]) -> str | None:
    image = frontmatter.get("image")
    if isinstance(image, str):
        value = image.strip()
        return value or None
    if isinstance(image, dict):
        src = image.get("src")
        if isinstance(src, str):
            value = src.strip()
            return value or None
    return None


def hero_placeholder_allowlist_path(repo_root: Path) -> Path:
    return repo_root / HERO_PLACEHOLDER_ALLOWLIST_SUBPATH


def deleted_route_smoke_checks_path(repo_root: Path) -> Path:
    return repo_root / DELETED_ROUTE_SMOKE_CHECKS_SUBPATH


def refinery_manifest_path(repo_root: Path) -> Path:
    return repo_root / POSTS_SUBPATH / MANIFEST_FILENAME


def _normalize_allowlist_entries(entries: dict[str, Any]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for rel_path, reason in sorted(entries.items()):
        if isinstance(reason, str):
            normalized[rel_path] = reason
    return normalized


def _write_placeholder_allowlist(allowlist_path: Path, entries: dict[str, Any]) -> None:
    payload = {"allowedPlaceholders": _normalize_allowlist_entries(entries)}
    allowlist_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _load_refinery_manifest(manifest_path: Path) -> dict[str, str]:
    if not manifest_path.exists():
        return {}

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}

    normalized: dict[str, str] = {}
    for article_id, file_name in payload.items():
        if isinstance(article_id, str) and isinstance(file_name, str):
            normalized[article_id] = file_name
    return normalized


def _write_refinery_manifest(manifest_path: Path, entries: dict[str, str]) -> None:
    manifest_path.write_text(
        json.dumps(dict(sorted(entries.items())), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def remove_hero_placeholder_allowlist_entry(repo_root: Path, rel_path: str) -> bool:
    allowlist_path = hero_placeholder_allowlist_path(repo_root)
    if not allowlist_path.exists():
        return False

    payload = json.loads(allowlist_path.read_text(encoding="utf-8"))
    entries = payload.get("allowedPlaceholders")
    if not isinstance(entries, dict):
        return False

    if rel_path not in entries:
        return False

    updated_entries = dict(entries)
    del updated_entries[rel_path]
    _write_placeholder_allowlist(allowlist_path, updated_entries)
    return True


def prune_refinery_manifest_for_post(
    repo_root: Path, *, file_name: str, refinery_id: str | None = None
) -> list[str]:
    manifest_path = refinery_manifest_path(repo_root)
    manifest_entries = _load_refinery_manifest(manifest_path)
    if not manifest_entries:
        return []

    removed_keys: list[str] = []
    updated_entries = dict(manifest_entries)

    if refinery_id:
        normalized_id = str(refinery_id).strip()
        if updated_entries.get(normalized_id) == file_name:
            removed_keys.append(normalized_id)
            del updated_entries[normalized_id]

    for article_id, manifest_file_name in list(updated_entries.items()):
        if manifest_file_name == file_name and article_id not in removed_keys:
            removed_keys.append(article_id)
            del updated_entries[article_id]

    if removed_keys:
        _write_refinery_manifest(manifest_path, updated_entries)

    return sorted(removed_keys)


def prune_hero_placeholder_allowlist_for_post(repo_root: Path, post_file: Path) -> bool:
    resolved_repo_root = repo_root.resolve()

    try:
        rel_path = post_file.resolve().relative_to(resolved_repo_root).as_posix()
    except ValueError:
        return False

    if not post_file.exists():
        return remove_hero_placeholder_allowlist_entry(resolved_repo_root, rel_path)

    frontmatter = parse_frontmatter_file(post_file)
    image_src = get_post_image_source(frontmatter)
    if image_src == DEFAULT_HERO_IMAGE:
        return False

    return remove_hero_placeholder_allowlist_entry(resolved_repo_root, rel_path)


def _slugify_segment(value: str) -> str:
    return slugify(value)


def normalize_route_path(route_path: str) -> str:
    stripped = str(route_path or "").strip()
    if not stripped:
        return ""
    normalized = f"/{stripped.strip('/')}/"
    return normalized.replace("//", "/")


def infer_published_article_route(article: PublishedArticleRecord) -> str | None:
    frontmatter_permalink = article.frontmatter.get("permalink")
    if isinstance(frontmatter_permalink, str) and frontmatter_permalink.strip():
        return normalize_route_path(frontmatter_permalink)

    categories = article.frontmatter.get("categories")
    if not isinstance(categories, list) or not categories:
        return None

    category = categories[0]
    if not isinstance(category, str) or not category.strip():
        return None

    stem = Path(article.file_name).stem.strip()
    category_slug = _slugify_segment(category)
    if not stem or not category_slug:
        return None

    return normalize_route_path(f"/{category_slug}/{stem}/")


def append_deleted_route_smoke_check(
    repo_root: Path,
    *,
    route_path: str,
    file_name: str,
    reason: str,
) -> bool:
    normalized_path = normalize_route_path(route_path)
    if not normalized_path:
        return False

    checks_path = deleted_route_smoke_checks_path(repo_root)
    payload: dict[str, Any] = {"routes": []}
    if checks_path.exists():
        existing_payload = json.loads(checks_path.read_text(encoding="utf-8"))
        if isinstance(existing_payload, dict):
            payload = existing_payload

    routes = payload.get("routes")
    if not isinstance(routes, list):
        routes = []

    updated_routes = [
        entry
        for entry in routes
        if isinstance(entry, dict)
        and normalize_route_path(entry.get("path", "")) != normalized_path
    ]
    updated_routes.append(
        {
            "path": normalized_path,
            "file_name": file_name,
            "reason": reason,
            "deleted_at": datetime.now(UTC)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
        }
    )
    payload["routes"] = sorted(
        updated_routes, key=lambda entry: str(entry.get("path", ""))
    )
    checks_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return True


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


def get_repo_head_sha(repo_root: Path) -> str | None:
    try:
        repo = git.Repo(repo_root)
        return repo.head.commit.hexsha
    except Exception:
        return None


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
    prefer_remote_checkout: bool = False,
) -> PublishedContentSnapshot:
    if not prefer_remote_checkout:
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


def find_published_article_by_file_name(
    posts_dir: Path, file_name: str
) -> PublishedArticleRecord | None:
    target_name = Path(str(file_name).strip()).name
    if not target_name:
        return None

    for article in load_published_articles(posts_dir):
        if article.file_name == target_name:
            return article
    return None


def _parse_repo_owner_and_name(target_repo_url: str) -> tuple[str, str] | None:
    normalized = normalize_repo_url(target_repo_url)
    if not normalized.startswith("github.com/"):
        return None

    remainder = normalized.split("/", 1)[1]
    owner, _, repo_name = remainder.partition("/")
    if not owner or not repo_name:
        return None
    return owner, repo_name


def _parse_github_pr_number(pr_url: str, target_repo_url: str) -> int | None:
    parsed = urlparse(str(pr_url or "").strip())
    repo_identity = _parse_repo_owner_and_name(target_repo_url)
    if repo_identity is None:
        return None

    owner, repo_name = repo_identity
    path_parts = [part for part in parsed.path.split("/") if part]
    if (
        parsed.hostname != "github.com"
        or len(path_parts) < 4
        or path_parts[0].lower() != owner.lower()
        or path_parts[1].lower() != repo_name.lower()
        or path_parts[2] != "pull"
    ):
        return None

    try:
        return int(path_parts[3])
    except (TypeError, ValueError):
        return None


def fetch_frontend_pr_check_health(
    *,
    target_repo_url: str,
    pr_url: str,
    github_token: str = "",
    required_workflows: Iterable[str] = FRONTEND_REQUIRED_PUBLICATION_WORKFLOWS,
) -> FrontendPrCheckStatus | None:
    repo_identity = _parse_repo_owner_and_name(target_repo_url)
    if repo_identity is None:
        return None

    pr_number = _parse_github_pr_number(pr_url, target_repo_url)
    if pr_number is None:
        return None

    owner, repo_name = repo_identity
    required = tuple(
        str(name).strip() for name in required_workflows if str(name).strip()
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    pr_response = requests.get(  # noqa: S113
        f"https://api.github.com/repos/{owner}/{repo_name}/pulls/{pr_number}",
        headers=headers,
        timeout=10,
    )
    pr_response.raise_for_status()
    pr_payload = pr_response.json()
    head_payload = pr_payload.get("head") if isinstance(pr_payload, dict) else {}
    head_sha = str((head_payload or {}).get("sha") or "") or None
    branch = str((head_payload or {}).get("ref") or "") or None

    workflow_runs: list[dict[str, Any]] = []
    if head_sha:
        run_params: dict[str, Any] = {"head_sha": head_sha, "per_page": 50}
        runs_response = requests.get(  # noqa: S113
            f"https://api.github.com/repos/{owner}/{repo_name}/actions/runs",
            params=run_params,
            headers=headers,
            timeout=10,
        )
        runs_response.raise_for_status()
        raw_runs = runs_response.json().get("workflow_runs", [])
        if isinstance(raw_runs, list):
            workflow_runs = [run for run in raw_runs if isinstance(run, dict)]

    latest_run_by_name: dict[str, dict[str, Any]] = {}
    for run in workflow_runs:
        run_name = str(run.get("name") or "").strip()
        if not run_name or run_name in latest_run_by_name:
            continue
        latest_run_by_name[run_name] = run

    workflow_conclusions: dict[str, str | None] = {}
    for workflow_name in required:
        workflow_run = latest_run_by_name.get(workflow_name)
        if workflow_run is None:
            workflow_conclusions[workflow_name] = None
            continue

        status = str(workflow_run.get("status") or "").strip()
        conclusion = str(workflow_run.get("conclusion") or "").strip() or None
        workflow_conclusions[workflow_name] = (
            conclusion if status == "completed" else "pending"
        )

    is_publish_ready = bool(
        str(pr_payload.get("state") or "").strip() == "open"
        and required
        and all(workflow_conclusions.get(name) == "success" for name in required)
    )

    return FrontendPrCheckStatus(
        pr_url=pr_url,
        pr_number=pr_number,
        head_sha=head_sha,
        branch=branch,
        state=str(pr_payload.get("state") or "").strip() or None,
        mergeable_state=str(pr_payload.get("mergeable_state") or "").strip() or None,
        required_workflows=required,
        workflow_conclusions=workflow_conclusions,
        is_publish_ready=is_publish_ready,
    )


def fetch_pages_deploy_health(
    *,
    target_repo_url: str,
    current_repo_sha: str | None,
    github_token: str = "",
    branch: str = "main",
) -> DeployHealthStatus | None:
    repo_identity = _parse_repo_owner_and_name(target_repo_url)
    if repo_identity is None:
        return None

    owner, repo_name = repo_identity
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    deploy_params: dict[str, Any] = {"branch": branch, "per_page": 10}
    response = requests.get(  # noqa: S113
        f"https://api.github.com/repos/{owner}/{repo_name}/actions/workflows/deploy.yml/runs",
        params=deploy_params,
        headers=headers,
        timeout=10,
    )
    response.raise_for_status()
    workflow_runs = response.json().get("workflow_runs", [])
    if not isinstance(workflow_runs, list):
        return None

    latest_run = workflow_runs[0] if workflow_runs else {}
    latest_success = next(
        (
            run
            for run in workflow_runs
            if isinstance(run, dict) and run.get("conclusion") == "success"
        ),
        {},
    )

    latest_successful_sha = str(latest_success.get("head_sha") or "") or None
    latest_run_sha = str(latest_run.get("head_sha") or "") or None
    return DeployHealthStatus(
        branch=branch,
        current_repo_sha=current_repo_sha,
        latest_run_sha=latest_run_sha,
        latest_run_conclusion=str(latest_run.get("conclusion") or "") or None,
        latest_run_url=str(latest_run.get("html_url") or "") or None,
        latest_successful_sha=latest_successful_sha,
        latest_successful_url=str(latest_success.get("html_url") or "") or None,
        is_live_stale=bool(
            current_repo_sha
            and latest_successful_sha
            and current_repo_sha != latest_successful_sha
        ),
    )


def reset_one_article(
    repo_root: Path,
    article: PublishedArticleRecord,
    db_manager: Any,
) -> None:
    """
    Reset a single published article: remove from git index, unlink file,
    commit, push, then delete DB rows.

    **Divergence-bug fix (plan 017):** DB rows are only deleted *after* the
    git push succeeds. If any step before the DB delete raises, the DB
    rows remain intact and the article can be retried. The old batched
    approach deleted DB rows first, then unlinked the file — if unlink
    failed, DB/file/git diverged.

    Args:
        repo_root: The target repo root (a git working tree).
        article: The article to reset.
        db_manager: A database manager with ``delete_article(id)``.

    Raises:
        Exception: If any step fails. The caller (``run_bulk``) captures
            the exception and continues to the next item.
    """
    repo = git.Repo(repo_root)

    # 1. Remove from git index + unlink file
    try:
        rel_path = str(article.file_path.relative_to(repo_root))
    except ValueError:
        # file_path is not under repo_root — use the absolute path
        rel_path = str(article.file_path)
    repo.index.remove([rel_path])
    article.file_path.unlink()

    # 2. Commit + push (per-item, not batched)
    repo.index.commit(f"Deleted (Reset) {article.file_name}")
    repo.remotes.origin.push()

    # 3. Only now delete DB rows — the git push succeeded, so the
    #    remote is in sync. If this raises, the remote is already
    #    updated and the DB rows can be cleaned up separately.
    if article.refinery_id:
        try:
            db_manager.delete_article(str(article.refinery_id))
            db_manager.delete_article(f"{article.refinery_id}.md")
        except Exception:
            # The remote is already updated; log but don't raise —
            # the article is effectively reset even if DB cleanup
            # needs a separate pass.
            logger.warning(
                "Remote updated but DB cleanup failed for %s",
                article.refinery_id,
                exc_info=True,
            )


def resolve_published_refinery_ids(
    *,
    target_repo_url: str,
    collector_repo_root: Path,
    temp_target_dir: Path,
    github_token: str = "",
) -> set[str]:
    """Return the set of refinery_ids currently published in the target repo.

    Uses the published-content snapshot (manifest + frontmatter scan of the
    target checkout/clone). This covers articles published from exports whose
    refinery_id is the title (non-numeric), which a DB-only
    is_article_in_flight_or_done() check cannot see (2026-08-12 regression:
    re-selecting an already-published export article re-ran the pipeline and
    created a duplicate PR).

    Best-effort: any failure (no checkout, no token, clone error) returns an
    empty set so callers fall back to the DB-only check.
    """
    if not target_repo_url:
        return set()
    try:
        snapshot = resolve_published_content_snapshot(
            target_repo_url=target_repo_url,
            collector_repo_root=collector_repo_root,
            temp_target_dir=temp_target_dir,
            github_token=github_token,
            refresh_clone=False,
            prefer_remote_checkout=True,
        )
    except Exception:  # defensive UI path
        logger.warning(
            "Could not resolve published refinery_ids for %s",
            target_repo_url,
            exc_info=True,
        )
        return set()
    return {str(a.refinery_id).strip() for a in snapshot.articles if a.refinery_id}
