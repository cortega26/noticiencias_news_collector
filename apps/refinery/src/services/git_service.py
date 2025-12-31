import git
import os
import shutil
import uuid
import requests
from pathlib import Path
from src.utils.logger import setup_logger

logger = setup_logger("GitService")

class GitHandler:
    def __init__(self, github_token: str):
        self.github_token = github_token
        self.headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github.v3+json"
        }

    def _cleanup_dir(self, path: Path):
        """Removes a directory if it exists."""
        if path.exists():
            # Handle readonly files on Windows
            def on_rm_error(func, path, exc_info):
                os.chmod(path, 0o777)
                func(path)
            shutil.rmtree(path, onerror=on_rm_error)

    def clone_repo(self, repo_url: str, target_dir: Path) -> git.Repo:
        """Clones a repository to a target directory.
        Since we might need to authenticate for push, we can inject token into URL if needed,
        but for public clone likely not needed. For push we will need it.
        We will assume the user has git credentials configured OR we inject token.
        For safety/simplicity in this script, we can inject token into the remote URL for the target repo.
        """
        self._cleanup_dir(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        
        # Inject token into URL for authenticated operations on target repo
        # Be careful not to log this URL
        auth_url = repo_url
        if "github.com" in repo_url and self.github_token:
            repo_part = repo_url.split("github.com/")[-1]
            auth_url = f"https://{self.github_token}@github.com/{repo_part}"

        logger.info(f"Cloning {repo_url} to {target_dir}...")
        return git.Repo.clone_from(auth_url, target_dir)

    def create_branch(self, repo: git.Repo, branch_prefix: str = "news/article") -> str:
        """Creates a new branch with a unique name."""
        branch_name = f"{branch_prefix}-{uuid.uuid4().hex[:8]}"
        new_branch = repo.create_head(branch_name)
        new_branch.checkout()
        logger.info(f"Created and checked out branch: {branch_name}")
        return branch_name

    def commit_and_push(self, repo: git.Repo, message: str, branch_name: str):
        """Commits all changes and pushes to the remote."""
        if not repo.is_dirty(untracked_files=True):
            logger.warning("No changes to commit.")
            return

        repo.git.add(A=True)
        repo.index.commit(message)
        logger.info(f"Committed changes: {message}")
        
        origin = repo.remote(name='origin')
        origin.push(branch_name)
        logger.info(f"Pushed branch {branch_name} to origin.")

    def create_pull_request(self, repo_url: str, branch_name: str, title: str, body: str, base_branch: str = "main") -> str:
        """Creates a Pull Request via GitHub API."""
        # Extract owner and repo from URL
        # URL format: https://github.com/owner/repo.git or similar
        clean_url = repo_url.rstrip(".git")
        parts = clean_url.split("/")
        owner = parts[-2]
        repo_name = parts[-1]
        
        api_url = f"https://api.github.com/repos/{owner}/{repo_name}/pulls"
        
        payload = {
            "title": title,
            "body": body,
            "head": branch_name,
            "base": base_branch
        }
        
        response = requests.post(api_url, json=payload, headers=self.headers)
        
        if response.status_code == 201:
            pr_url = response.json().get("html_url")
            logger.info(f"Pull Request created successfully: {pr_url}")
            return pr_url
        else:
            logger.error(f"Failed to create PR: {response.status_code} - {response.text}")
            raise Exception(f"PR Creation failed: {response.text}")
