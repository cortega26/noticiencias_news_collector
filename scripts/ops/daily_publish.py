#!/usr/bin/env python3
"""Plan 203: publish one article a day from the focus topics.

Runs once a day from a systemd timer, through the running admin API:

1. skip if today's article was already launched (marker file) or a
   publication is active;
2. run a collection cycle and wait for it;
3. pick the best ready-to-publish candidate in ``[daily_publish].categories``
   with a score of at least ``min_score``;
4. start its publication. The article still lands as a frontend PR for the
   owner to review; a missing image is drawn by the image generator (plan 202).

Exit codes: 0 done or nothing to do, 1 an API step failed (including a 503
when admin auth is required but ADMIN_API_KEY is unset), 2 the admin API is
not reachable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MARKER_DIR = REPO_ROOT / "data" / "daily-publish"
POLL_SECONDS = 20


class DailyPublishError(RuntimeError):
    """An admin API step failed; the message says which."""


class AdminClient:
    def __init__(self, base_url: str, token: str = "", session: Any = None):
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        if token:  # a development-tier admin accepts local calls without one
            self.session.headers["Authorization"] = f"Bearer {token}"

    def _call(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.session.request(
            method, f"{self.base_url}{path}", timeout=60, **kwargs
        )
        if response.status_code >= 400 and response.status_code != 409:
            raise DailyPublishError(f"{method} {path} -> HTTP {response.status_code}")
        return response.json()

    def get(self, path: str, **params: Any) -> dict[str, Any]:
        return self._call("GET", path, params=params or None)

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._call("POST", path, json=payload)


def pick_candidate(
    items: list[dict[str, Any]], categories: list[str], min_score: float
) -> dict[str, Any] | None:
    """Best-scored publishable item in the focus topics, or None."""
    allowed = {c.lower() for c in categories}
    eligible = [
        item
        for item in items
        if item.get("publishable")
        and not item.get("published_url")
        and str(item.get("category") or "").lower() in allowed
        and (item.get("final_score") or 0.0) >= min_score
    ]
    return max(eligible, key=lambda i: i.get("final_score") or 0.0, default=None)


def wait_for_collection(
    client: AdminClient,
    timeout_minutes: int,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_minutes * 60
    while True:
        status = client.get("/v1/admin/collect/status")
        if status.get("status") in {"succeeded", "failed", "cancelled", "interrupted"}:
            return status
        if time.monotonic() > deadline:
            raise DailyPublishError(
                f"Collection still {status.get('status')} after {timeout_minutes} min"
            )
        sleep(POLL_SECONDS)


def run(
    client: AdminClient,
    cfg: Any,
    *,
    today: str,
    marker_dir: Path = MARKER_DIR,
    collect: bool = True,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    marker = marker_dir / f"{today}.json"
    if marker.exists():
        return {"outcome": "already_done", "marker": str(marker)}
    if client.get("/v1/admin/publish/status").get("active"):
        return {"outcome": "publication_active"}

    if collect:
        client.post("/v1/admin/collect", {"dry_run": False})
        collection = wait_for_collection(client, cfg.collect_timeout_minutes, sleep)
        if collection.get("status") != "succeeded":
            # A failed cycle still leaves earlier candidates; carry on.
            print(f"Collection ended {collection.get('status')}; using existing pool")

    listing = client.get("/v1/admin/articles", status="publishable", page_size=50)
    candidate = pick_candidate(listing.get("data", []), cfg.categories, cfg.min_score)
    if candidate is None:
        return {"outcome": "no_candidate", "categories": cfg.categories}

    started = client.post("/v1/admin/publish", {"article_id": candidate["id"]})
    result = {
        "outcome": "publishing",
        "article_id": candidate["id"],
        "title": candidate.get("title"),
        "category": candidate.get("category"),
        "final_score": candidate.get("final_score"),
        "run_id": started.get("run_id"),
        "run_status": started.get("status"),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--no-collect", action="store_true", help="Skip the collection cycle."
    )
    args = parser.parse_args(argv)

    from noticiencias.config_manager import load_config

    cfg = load_config().daily_publish
    if not cfg.enabled:
        print("daily_publish disabled in config.toml; nothing to do")
        return 0
    client = AdminClient(cfg.api_url, os.environ.get("ADMIN_API_KEY", ""))
    try:
        result = run(
            client,
            cfg,
            today=datetime.now().strftime("%Y-%m-%d"),
            # Read at call time: the `run` default is bound at definition.
            marker_dir=MARKER_DIR,
            collect=not args.no_collect,
        )
    except (requests.ConnectionError, requests.Timeout):
        # Also covers an API that accepts connections but never answers.
        print(f"Admin API not reachable at {cfg.api_url}", file=sys.stderr)
        return 2
    except DailyPublishError as err:
        print(f"Daily publish failed: {err}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
