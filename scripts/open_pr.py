
import sys
import os

# Add project root to path
sys.path.insert(0, "/home/cortega26/noticiencias_news_collector")

from news_collector.components.publishing.github_publisher import GitHubPublisher
from dotenv import load_dotenv

def main():
    # Load env
    load_dotenv()
    
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("❌ GITHUB_TOKEN not found in environment.")
        sys.exit(1)
        
    publisher = GitHubPublisher(github_token=token)
    
    repo_url = "https://github.com/cortega26/noticiencias.git"
    branch_name = "content/update-2026-01-25-article-86"
    title = "feat: publish article 206 with corrected title"
    body = """Automated correction by Refinery Agent.

- **Published:** Article 206 (Corrected Title)
- **Removed:** Article 238 (Incorrectly published)

This PR synchronizes the repository with the intended state.
"""
    
    try:
        pr_url = publisher.create_pull_request(
            repo_url=repo_url,
            branch_name=branch_name,
            title=title,
            body=body,
            base_branch="main" 
        )
        print(f"✅ Pull Request Created: {pr_url}")
    except Exception as e:
        print(f"❌ Failed to create PR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
