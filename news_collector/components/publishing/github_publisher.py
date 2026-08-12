"""
Module role: Handles interactions with Git and GitHub to safely publish articles to remote repositories.

Inputs:
- GitHub authentication tokens.
- Repository URLs, target directories, branch names, and commit messages.

Outputs:
- Cloned Git repository objects.
- Branch name strings and GitHub Pull Request URLs.

Side effects:
- Creates and manages temporary askpass scripts on the filesystem for Git authentication.
- Modifies local filesystems by cloning repositories and cleaning up directories.
- Executes Git commands (clone, checkout, pull, commit, push) and HTTP POST requests to GitHub APIs.

Invariants:
- Attempts to prevent authentication tokens from being persisted in logs or permanently on disk.
- Branch names are deterministically generated when explicit names are provided.
- Repositories are cleanly initialized by removing the target directory prior to cloning.

Failure modes:
- Raises RuntimeError if a GitHub token is missing when required.
- Raises exceptions if GitHub Pull Request creation API calls fail with non-201 HTTP status.
- Logs warnings if there are no untracked or modified files to commit.
"""

import contextlib
import os
import shutil
import tempfile
import uuid
from pathlib import Path

import git
import requests

from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger("components.publishing.github_publisher")
DEFAULT_BASE_BRANCH = "main"
MAX_NON_FAST_FORWARD_RETRIES = 1


class GitHubPublisher:
    """
    Handles interactions with Git and GitHub for publishing articles.
    Formerly 'GitHandler' in the refinery app.
    """

    def __init__(self, github_token: str = "", base_branch: str = DEFAULT_BASE_BRANCH):
        self.github_token = github_token or os.environ.get("GITHUB_TOKEN", "")
        self.base_branch = base_branch or DEFAULT_BASE_BRANCH
        self._askpass_path: Path | None = None
        self.headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github.v3+json",
        }

    def _strip_credentials(self, repo_url: str) -> str:
        """Remove embedded credentials from URLs for safe logging."""
        if "://" in repo_url and "@" in repo_url.split("://", 1)[1]:
            scheme, rest = repo_url.split("://", 1)
            rest = rest.split("@", 1)[1]
            return f"{scheme}://{rest}"
        return repo_url

    def _safe_repo_url(self, repo_url: str) -> str:
        """Ensure the remote URL never embeds a token."""
        if not self.github_token:
            return repo_url
        if repo_url.startswith("git@github.com:"):
            repo_part = repo_url.split("git@github.com:", 1)[1]
            return f"https://x-access-token@github.com/{repo_part}"
        if "github.com" in repo_url:
            repo_part = repo_url.split("github.com/", 1)[1]
            return f"https://x-access-token@github.com/{repo_part}"
        return repo_url

    def _ensure_askpass_script(self) -> Path:
        """Create a temporary askpass script for Git operations."""
        if self._askpass_path and self._askpass_path.exists():
            return self._askpass_path
        if not self.github_token:
            raise RuntimeError(
                "GitHub token required for authenticated git operations."
            )

        suffix = ".cmd" if os.name == "nt" else ".sh"
        script_path = (
            Path(tempfile.gettempdir())
            / f"noticiencias_askpass_{uuid.uuid4().hex}{suffix}"
        )
        if os.name == "nt":
            content = "@echo off\n"
            content += "echo %NOTICIENCIAS_GIT_TOKEN%\n"
        else:
            content = "#!/bin/sh\n"
            content += "printf '%s' \"$NOTICIENCIAS_GIT_TOKEN\"\n"
        script_path.write_text(content, encoding="utf-8")
        if os.name != "nt":
            script_path.chmod(0o700)
        self._askpass_path = script_path
        return script_path

    def _auth_env(self) -> dict[str, str]:
        """Build a safe auth environment for Git without persisting tokens."""
        if not self.github_token:
            return {}
        askpass_path = self._ensure_askpass_script()
        env = os.environ.copy()
        env["NOTICIENCIAS_GIT_TOKEN"] = self.github_token
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_ASKPASS"] = str(askpass_path)
        env["GIT_ASKPASS_REQUIRE"] = "force"
        return env

    @staticmethod
    def _remote_branch_exists(repo: git.Repo, branch_name: str) -> bool:
        remote_ref = f"origin/{branch_name}"
        return any(ref.name == remote_ref for ref in repo.refs)

    @staticmethod
    def _is_non_fast_forward(error: git.GitCommandError) -> bool:
        stderr = (error.stderr or "").lower()
        stdout = (error.stdout or "").lower()
        combined = f"{stderr}\n{stdout}"
        if "non-fast-forward" in combined:
            return True
        if "tip of your current branch is behind" in combined:
            return True
        if (
            "updates were rejected" in combined
            and "failed to push some refs" in combined
        ):
            return True
        return "fetch first" in combined

    @staticmethod
    def _get_conflict_files(repo: git.Repo) -> list[str]:
        try:
            conflicted = repo.git.diff("--name-only", "--diff-filter=U")
        except git.GitCommandError:
            return []
        return [line.strip() for line in conflicted.splitlines() if line.strip()]

    @staticmethod
    def _get_git_state_markers(repo: git.Repo) -> list[str]:
        markers: list[str] = []
        try:
            git_dir = Path(str(repo.git_dir))
        except Exception:  # noqa: BLE001
            return markers

        marker_names = (
            "REBASE_HEAD",
            "rebase-apply",
            "rebase-merge",
            "MERGE_HEAD",
            "CHERRY_PICK_HEAD",
            "REVERT_HEAD",
        )
        for marker in marker_names:
            if (git_dir / marker).exists():
                markers.append(marker)
        return markers

    def _ensure_clean_exit_state(
        self,
        repo: git.Repo,
        branch_name: str,
        env: dict[str, str] | None,
    ) -> None:
        for abort_command in ("rebase", "merge", "cherry_pick", "revert"):
            with contextlib.suppress(git.GitCommandError):
                getattr(repo.git, abort_command)("--abort", env=env or None)

        active_branch = None
        try:
            active_branch = repo.active_branch.name
        except Exception:  # noqa: BLE001
            active_branch = None

        if active_branch != branch_name:
            try:
                repo.git.checkout(branch_name, env=env or None)
            except git.GitCommandError:
                # Deterministic recovery fallback when target branch is unavailable.
                repo.git.checkout(self.base_branch, env=env or None)

        markers = self._get_git_state_markers(repo)
        if markers:
            marker_list = ", ".join(markers)
            raise RuntimeError(
                f"Repository still has in-progress git state after cleanup: {marker_list}"
            )

        if repo.is_dirty(untracked_files=True):
            raise RuntimeError("Repository working tree is dirty after cleanup.")

    @contextlib.contextmanager
    def _cleanup_on_failure(
        self,
        *,
        repo: git.Repo,
        branch_name: str,
        env: dict[str, str] | None,
        operation: str,
    ):
        failure: Exception | None = None
        try:
            yield
        except Exception as exc:  # noqa: BLE001
            failure = exc
            raise
        finally:
            if failure is not None:
                try:
                    self._ensure_clean_exit_state(repo, branch_name, env)
                except Exception as cleanup_error:  # noqa: BLE001
                    raise RuntimeError(
                        f"{operation} failed for branch {branch_name}. "
                        f"Cleanup verification failed: {cleanup_error}"
                    ) from failure

    def _cleanup_dir(self, path: Path):
        """Removes a directory if it exists."""
        if path.exists():
            # Handle readonly files on Windows
            def on_rm_error(func, path, exc_info):
                os.chmod(path, 0o700)  # nosemgrep
                func(path)

            shutil.rmtree(path, onerror=on_rm_error)

    def clone_repo(self, repo_url: str, target_dir: Path) -> git.Repo:
        """Clones a repository to a target directory."""
        self._cleanup_dir(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        auth_url = self._safe_repo_url(repo_url)
        env = self._auth_env()

        logger.info(f"Cloning {self._strip_credentials(repo_url)} to {target_dir}...")
        return git.Repo.clone_from(auth_url, target_dir, env=env or None)

    def create_branch(
        self,
        repo: git.Repo,
        branch_prefix: str = "news/article",
        explicit_name: str | None = None,
        base_branch: str | None = None,
    ) -> str:
        """
        Creates a new branch.

        Args:
            repo: The git repository object.
            branch_prefix: Prefix for the branch name (e.g. 'news/article').
            explicit_name: Optional explicit suffix (e.g. article slug) for deterministic naming.
                          If None, a random UUID is used.
        """
        if explicit_name:
            # Sanitize explicit name just in case
            safe_suffix = "".join(
                c if c.isalnum() or c in "-_" else "-" for c in explicit_name
            ).strip("-")
            branch_name = f"{branch_prefix}-{safe_suffix}"
        else:
            branch_name = f"{branch_prefix}-{uuid.uuid4().hex[:8]}"

        env = self._auth_env()
        with self._cleanup_on_failure(
            repo=repo,
            branch_name=branch_name,
            env=env,
            operation="Branch setup",
        ):
            repo.git.fetch("origin", "--prune", env=env or None)

            remote_ref = f"origin/{branch_name}"
            if self._remote_branch_exists(repo, branch_name):
                logger.info(
                    f"Remote branch {remote_ref} exists. Checking out local branch from remote tip."
                )
                repo.git.checkout("-B", branch_name, remote_ref, env=env or None)
                repo.git.rebase(remote_ref, env=env or None)
            else:
                selected_base = (
                    base_branch or self.base_branch
                ).strip() or self.base_branch
                deterministic_base_ref = f"origin/{selected_base}"
                if not any(ref.name == deterministic_base_ref for ref in repo.refs):
                    raise RuntimeError(
                        f"Deterministic base ref {deterministic_base_ref} not found. "
                        "Refusing to reuse potential stale local branch state."
                    )
                logger.info(
                    f"Remote branch {remote_ref} does not exist. Resetting {branch_name} "
                    f"to deterministic base {deterministic_base_ref}."
                )
                # Deterministic invariant: when origin/<branch> is absent, we always
                # reset/create the local branch from the deterministic base ref.
                repo.git.checkout(
                    "-B", branch_name, deterministic_base_ref, env=env or None
                )

        logger.info(f"Checked out branch: {branch_name}")
        return branch_name

    def commit_and_push(self, repo: git.Repo, message: str, branch_name: str):
        """Commits all changes and pushes to the remote."""
        env = self._auth_env()
        remote_ref = f"origin/{branch_name}"
        retry_attempts = 0

        with self._cleanup_on_failure(
            repo=repo,
            branch_name=branch_name,
            env=env,
            operation="Commit/push",
        ):
            if not repo.is_dirty(untracked_files=True):
                logger.warning("No changes to commit.")
                return

            repo.git.add(A=True)
            repo.index.commit(message)
            logger.info(f"Committed changes: {message}")

            while True:
                try:
                    repo.git.push("origin", branch_name, env=env or None)
                    if retry_attempts == 0:
                        logger.info(f"Pushed branch {branch_name} to origin.")
                    else:
                        logger.info(
                            f"Pushed branch {branch_name} to origin after rebase retry."
                        )
                    return
                except git.GitCommandError as push_error:
                    if not self._is_non_fast_forward(push_error):
                        raise RuntimeError(
                            f"Push failed for branch {branch_name}. "
                            "No force push was attempted."
                        ) from push_error

                    if retry_attempts >= MAX_NON_FAST_FORWARD_RETRIES:
                        raise RuntimeError(
                            f"Push failed for branch {branch_name}: remote advanced again "
                            "during retry. No force push was attempted."
                        ) from push_error

                    retry_attempts += 1
                    logger.warning(
                        f"Push rejected for {branch_name} (non-fast-forward). "
                        "Retrying once with fetch + rebase; no force push will be used."
                    )

                    try:
                        repo.git.fetch("origin", "--prune", env=env or None)
                        # Remote history is never rewritten: we only rebase local commits
                        # onto origin/<branch> and retry push exactly once.
                        repo.git.rebase(remote_ref, env=env or None)
                    except git.GitCommandError as rebase_error:
                        conflict_files = self._get_conflict_files(repo)
                        conflict_list = (
                            ", ".join(conflict_files) if conflict_files else "(unknown)"
                        )
                        raise RuntimeError(
                            f"Push failed for branch {branch_name}: remote branch advanced "
                            f"and automatic rebase conflicted. Conflicting files: {conflict_list}. "
                            "No force push was attempted."
                        ) from rebase_error

    def create_pull_request(
        self,
        repo_url: str,
        branch_name: str,
        title: str,
        body: str,
        base_branch: str | None = None,
    ) -> str:
        """Creates a Pull Request via GitHub API."""
        # Extract owner and repo from URL
        clean_url = repo_url.rstrip(".git")
        parts = clean_url.split("/")
        owner = parts[-2]
        repo_name = parts[-1]

        api_url = f"https://api.github.com/repos/{owner}/{repo_name}/pulls"

        payload = {
            "title": title,
            "body": body,
            "head": branch_name,
            "base": (base_branch or self.base_branch).strip() or self.base_branch,
        }

        response = requests.post(  # noqa: S113
            api_url, json=payload, headers=self.headers
        )

        if response.status_code == 201:
            pr_url = str(response.json().get("html_url", ""))
            logger.info(f"Pull Request created successfully: {pr_url}")
            return pr_url
        elif response.status_code == 422:
            # A-04 / F-0016: PR might already exist for this branch — try to recover
            logger.warning(
                f"PR creation returned 422 for branch {branch_name}. "
                "Checking for existing PR..."
            )
            search_url = f"https://api.github.com/repos/{owner}/{repo_name}/pulls"
            search_params = {"head": f"{owner}:{branch_name}", "state": "open"}
            search_response = requests.get(  # noqa: S113
                search_url, params=search_params, headers=self.headers
            )
            if search_response.status_code == 200:
                prs = search_response.json()
                if prs:
                    existing_url = str(prs[0].get("html_url", ""))
                    logger.info(
                        f"Recovered existing PR for branch {branch_name}: {existing_url}"
                    )
                    return existing_url
            # No existing PR found — raise original error
            logger.error(
                f"Failed to create PR (422, no existing PR found): {response.text}"
            )
            raise Exception(f"PR Creation failed: {response.text}")
        else:
            logger.error(
                f"Failed to create PR: {response.status_code} - {response.text}"
            )
            raise Exception(f"PR Creation failed: {response.text}")
