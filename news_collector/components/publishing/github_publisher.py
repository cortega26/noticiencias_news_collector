import os
import shutil
import tempfile
import uuid
from pathlib import Path

import git
import requests
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger("components.publishing.github_publisher")


class GitHubPublisher:
    """
    Handles interactions with Git and GitHub for publishing articles.
    Formerly 'GitHandler' in the refinery app.
    """

    def __init__(self, github_token: str):
        self.github_token = github_token
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

    def _cleanup_dir(self, path: Path):
        """Removes a directory if it exists."""
        if path.exists():
            # Handle readonly files on Windows
            def on_rm_error(func, path, exc_info):
                os.chmod(path, 0o700)
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

        # Check if branch exists to avoid error?
        # git.Repo.create_head will raise if it exists.
        # For idempotency, we should check.
        if branch_name in repo.heads:
            logger.info(f"Branch {branch_name} already exists. Checking it out.")
            new_branch = repo.heads[branch_name]
        else:
            new_branch = repo.create_head(branch_name)

        new_branch.checkout()
        logger.info(f"Checked out branch: {branch_name}")
        return branch_name

    def commit_and_push(self, repo: git.Repo, message: str, branch_name: str):
        """Commits all changes and pushes to the remote."""
        if not repo.is_dirty(untracked_files=True):
            logger.warning("No changes to commit.")
            return

        repo.git.add(A=True)
        repo.index.commit(message)
        logger.info(f"Committed changes: {message}")

        env = self._auth_env()
        repo.git.push("origin", branch_name, env=env or None)
        logger.info(f"Pushed branch {branch_name} to origin.")

    def create_pull_request(
        self,
        repo_url: str,
        branch_name: str,
        title: str,
        body: str,
        base_branch: str = "main",
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
            "base": base_branch,
        }

        response = requests.post(
            api_url, json=payload, headers=self.headers
        )  # noqa: S113

        if response.status_code == 201:
            pr_url = response.json().get("html_url")
            logger.info(f"Pull Request created successfully: {pr_url}")
            return pr_url
        else:
            logger.error(
                f"Failed to create PR: {response.status_code} - {response.text}"
            )
            raise Exception(f"PR Creation failed: {response.text}")
