"""
Reddit API collector — OAuth2 application-only (client-credentials) flow.

Collects posts from Reddit subreddits via the official JSON API.
The article `url` is the Reddit permalink so we never scrape linked
external articles (consistent with the paywalled-source removal policy).

Required env vars:
  REDDIT_CLIENT_ID      — from reddit.com/prefs/apps
  REDDIT_CLIENT_SECRET  — from reddit.com/prefs/apps

Without those variables the collector logs a warning and returns gracefully
with articles_found=0 so the rest of the pipeline is unaffected.
"""

import os
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import requests

from news_collector.config.settings import get_runtime_config
from news_collector.contracts import CollectorArticleModel
from news_collector.contracts.common import ArticleMetadataModel

from .base_collector import BaseCollector

if TYPE_CHECKING:
    from news_collector.utils.logger import NewsCollectorLogger

_TOKEN_ENDPOINT = "https://www.reddit.com/api/v1/access_token"  # noqa: S105
_API_BASE = "https://oauth.reddit.com"
_PERMALINK_BASE = "https://www.reddit.com"
_TOKEN_REFRESH_BUFFER_SECONDS = 60


class RedditCollector(BaseCollector):
    """Collects posts from Reddit subreddits via the official OAuth2 API."""

    def __init__(
        self,
        logger_factory: Optional["NewsCollectorLogger"] = None,
        health_tracker: Optional[Any] = None,
    ) -> None:
        super().__init__(logger_factory=logger_factory, health_tracker=health_tracker)
        cfg = get_runtime_config()
        self._client_id = os.getenv("REDDIT_CLIENT_ID", "")
        self._client_secret = os.getenv("REDDIT_CLIENT_SECRET", "")
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._user_agent: str = cfg.collection_config.get(
            "user_agent", "NoticienciasBot/1.0 (+https://noticiencias.com)"
        )

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def _fetch_token(self) -> bool:
        """Request a new application-only access token. Returns True on success."""
        try:
            resp = requests.post(
                _TOKEN_ENDPOINT,
                data={"grant_type": "client_credentials"},
                auth=(self._client_id, self._client_secret),
                headers={"User-Agent": self._user_agent},
                timeout=15,
            )
            resp.raise_for_status()
            payload = resp.json()
            self._token = payload["access_token"]
            expires_in = float(payload.get("expires_in", 3600))
            self._token_expires_at = (
                time.monotonic() + expires_in - _TOKEN_REFRESH_BUFFER_SECONDS
            )
            return True
        except Exception as exc:
            self._token = None
            self._token_expires_at = 0.0
            self._emit_log(
                "error",
                "collector.reddit.token_error",
                source_id="reddit",
                details={"error": str(exc)},
            )
            return False

    def _ensure_token(self) -> bool:
        if self._token and time.monotonic() < self._token_expires_at:
            return True
        return self._fetch_token()

    def _api_get(self, path: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        cfg = get_runtime_config()
        if not self._ensure_token():
            return None
        resp = requests.get(
            f"{_API_BASE}{path}",
            headers={
                "Authorization": f"Bearer {self._token}",
                "User-Agent": self._user_agent,
            },
            params=params,
            timeout=int(cfg.collection_config.get("request_timeout_seconds", 30)),
        )
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    # ------------------------------------------------------------------
    # Core collection
    # ------------------------------------------------------------------

    def collect_from_source(
        self, source_id: str, source_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        cfg = get_runtime_config()
        start_time = time.time()
        stats: Dict[str, Any] = {
            "source_id": source_id,
            "success": False,
            "articles_found": 0,
            "articles_saved": 0,
            "error_message": None,
            "processing_time": 0,
            "content_mode": source_config.get("content_mode", "summary_only"),
        }

        if source_config.get("status") == "blocked":
            stats["success"] = True
            stats["error_message"] = "Source blocked in config"
            stats["processing_time"] = round(time.time() - start_time, 3)
            return stats

        if not self._client_id or not self._client_secret:
            self._emit_log(
                "warning",
                "collector.reddit.no_credentials",
                source_id=source_id,
                details={
                    "hint": "Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in .env"
                },
            )
            stats["success"] = True
            stats["error_message"] = "Reddit credentials not configured — skipping"
            stats["processing_time"] = round(time.time() - start_time, 3)
            return stats

        try:
            subreddit = source_config.get("subreddit", "science")
            sort = source_config.get("sort", "new")
            limit = int(cfg.collection_config.get("max_articles_per_source", 5))
            # Over-fetch so filtering doesn't leave us empty
            fetch_limit = min(limit * 4, 25)

            self._enforce_domain_rate_limit(
                "oauth.reddit.com",
                robots_delay=None,
                source_min_delay=source_config.get("min_delay_seconds"),
            )

            self._emit_log(
                "info",
                "collector.reddit.fetch_start",
                source_id=source_id,
                details={"subreddit": subreddit, "sort": sort, "limit": fetch_limit},
            )

            data = self._api_get(
                f"/r/{subreddit}/{sort}",
                params={"limit": fetch_limit, "raw_json": 1},
            )

            if not data or "data" not in data:
                stats["error_message"] = "Empty or invalid API response"
                stats["processing_time"] = round(time.time() - start_time, 3)
                return stats

            posts = data["data"].get("children", [])
            stats["articles_found"] = len(posts)

            articles: List[CollectorArticleModel] = []
            for post in posts:
                article = self._post_to_article(post["data"], source_id, source_config)
                if article is not None:
                    articles.append(article)

            stats["articles_saved"] = self._filter_and_save_articles(
                source_id, articles, limit=limit
            )
            stats["success"] = True

        except Exception as exc:
            stats["error_message"] = str(exc)
            self._emit_log(
                "error",
                "collector.reddit.error",
                source_id=source_id,
                details={"error": str(exc)},
            )
        finally:
            stats["processing_time"] = round(time.time() - start_time, 3)

        return stats

    # ------------------------------------------------------------------
    # Post → article mapping
    # ------------------------------------------------------------------

    def _post_to_article(
        self,
        post: Dict[str, Any],
        source_id: str,
        source_config: Dict[str, Any],
    ) -> Optional[CollectorArticleModel]:
        try:
            raw_title = (post.get("title") or "").strip()
            if len(raw_title) < 10:
                return None  # Skip near-empty or removed posts

            permalink = f"{_PERMALINK_BASE}{post['permalink']}"
            linked_url = post.get("url") or permalink

            selftext = (post.get("selftext") or "").strip()
            if selftext in ("[removed]", "[deleted]"):
                selftext = ""

            summary = f"{raw_title}\n\n{selftext}".strip() if selftext else raw_title

            published_date = datetime.fromtimestamp(
                float(post.get("created_utc", time.time())), tz=timezone.utc
            )

            raw_author = post.get("author") or ""
            authors = (
                [raw_author]
                if raw_author and raw_author not in ("[deleted]", "AutoModerator")
                else []
            )

            metadata = ArticleMetadataModel(
                source_metadata={
                    "reddit_score": post.get("score"),
                    "reddit_num_comments": post.get("num_comments"),
                    "subreddit": post.get("subreddit"),
                    "flair": post.get("link_flair_text"),
                    "linked_url": linked_url if linked_url != permalink else None,
                },
                credibility_score=source_config.get("credibility_score"),
            )

            return CollectorArticleModel(
                url=permalink,  # type: ignore[arg-type]  # Pydantic coerces str → AnyHttpUrl
                original_url=linked_url if linked_url != permalink else None,
                title=raw_title,
                summary=summary,
                content=selftext or None,
                source_id=source_id,
                source_name=source_config.get("name", "Reddit"),
                category=source_config.get("category", "community_science"),
                published_date=published_date,
                authors=authors,
                language=source_config.get("language", "en"),
                content_mode="summary_only",
                # Reddit posts are inherently low-content — override Stage B thresholds
                min_summary_length_override=0,
                min_content_length_override=0,
                article_metadata=metadata,
            )
        except Exception as exc:
            self._emit_log(
                "warning",
                "collector.reddit.article_parse_error",
                source_id=source_id,
                details={"error": str(exc), "post_id": post.get("id")},
            )
            return None
