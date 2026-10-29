"""Plan 203: one article a day from the focus topics."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "ops" / "daily_publish.py"
spec = importlib.util.spec_from_file_location("daily_publish", SCRIPT)
assert spec is not None and spec.loader is not None
dp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dp)

CFG = SimpleNamespace(
    categories=["medicine", "biology", "technology", "artificial_intelligence"],
    min_score=0.5,
    collect_timeout_minutes=1,
)


def item(id_, category, score, **extra):
    return {
        "id": id_,
        "title": f"t{id_}",
        "category": category,
        "final_score": score,
        "publishable": True,
        "published_url": None,
        **extra,
    }


class FakeClient:
    def __init__(self, items, *, active=False, collect_states=("succeeded",)):
        self.items = items
        self.active = active
        self.collect_states = list(collect_states)
        self.posts = []

    def get(self, path, **params):
        if path == "/v1/admin/publish/status":
            return {"active": self.active}
        if path == "/v1/admin/collect/status":
            return {"status": self.collect_states.pop(0)}
        if path == "/v1/admin/articles":
            assert params == {"status": "publishable", "page_size": 50}
            return {"data": self.items}
        raise AssertionError(path)

    def post(self, path, payload):
        self.posts.append((path, payload))
        return {"run_id": "77", "status": "queued"}


def test_pick_candidate_filters_topic_score_and_state():
    items = [
        item(1, "space", 0.99),
        item(2, "medicine", 0.4),
        item(3, "Biology", 0.7),
        item(4, "technology", 0.9, published_url="https://x"),
        item(5, "artificial_intelligence", 0.8, publishable=False),
        item(6, "technology", 0.75),
    ]
    assert dp.pick_candidate(items, CFG.categories, 0.5)["id"] == 6
    assert dp.pick_candidate([item(1, "space", 0.9)], CFG.categories, 0.5) is None


def test_run_collects_publishes_and_marks_the_day(tmp_path):
    client = FakeClient(
        [item(3, "medicine", 0.8)], collect_states=["running", "succeeded"]
    )
    result = dp.run(
        client, CFG, today="2026-10-28", marker_dir=tmp_path, sleep=lambda s: None
    )
    assert result["outcome"] == "publishing" and result["article_id"] == 3
    assert client.posts == [
        ("/v1/admin/collect", {"dry_run": False}),
        ("/v1/admin/publish", {"article_id": 3}),
    ]
    marker = json.loads((tmp_path / "2026-10-28.json").read_text())
    assert marker["run_id"] == "77"
    # Same day again: nothing else happens.
    again = dp.run(client, CFG, today="2026-10-28", marker_dir=tmp_path)
    assert again["outcome"] == "already_done" and len(client.posts) == 2


def test_active_publication_skips_the_day(tmp_path):
    client = FakeClient([item(3, "medicine", 0.8)], active=True)
    assert (
        dp.run(client, CFG, today="d", marker_dir=tmp_path)["outcome"]
        == "publication_active"
    )
    assert client.posts == []


def test_no_candidate_publishes_nothing_and_leaves_no_marker(tmp_path):
    client = FakeClient([item(1, "space", 0.9)])
    result = dp.run(client, CFG, today="d", marker_dir=tmp_path, collect=False)
    assert result["outcome"] == "no_candidate"
    assert client.posts == [] and not list(tmp_path.iterdir())


def test_failed_collection_still_uses_the_existing_pool(tmp_path):
    client = FakeClient([item(3, "biology", 0.6)], collect_states=["failed"])
    result = dp.run(client, CFG, today="d", marker_dir=tmp_path, sleep=lambda s: None)
    assert result["outcome"] == "publishing"


def test_collection_timeout_raises(tmp_path, monkeypatch):
    client = FakeClient([], collect_states=["running"] * 5)
    clock = iter([0, 0, 10_000, 10_000])
    monkeypatch.setattr(dp.time, "monotonic", lambda: next(clock))
    with pytest.raises(dp.DailyPublishError, match="still running"):
        dp.run(client, CFG, today="d", marker_dir=tmp_path, sleep=lambda s: None)


class FakeResponse:
    def __init__(self, code, body):
        self.status_code = code
        self.body = body

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, code=200):
        self.headers = {}
        self.code = code
        self.calls = []

    def request(self, method, url, timeout, **kwargs):
        self.calls.append((method, url, kwargs))
        return FakeResponse(self.code, {"ok": True})


def test_client_sends_token_only_when_set():
    with_token = FakeSession()
    dp.AdminClient("http://h:1/", "k", session=with_token).get("/a", x=1)
    assert with_token.headers["Authorization"] == "Bearer k"
    assert with_token.calls[0][1] == "http://h:1/a"
    open_dev = FakeSession()
    dp.AdminClient("http://h:1", session=open_dev).post("/b", {"y": 2})
    assert "Authorization" not in open_dev.headers


def test_client_raises_on_http_errors_but_not_conflict():
    with pytest.raises(dp.DailyPublishError, match="HTTP 503"):
        dp.AdminClient("http://h", session=FakeSession(503)).get("/x")
    assert dp.AdminClient("http://h", session=FakeSession(409)).get("/x") == {
        "ok": True
    }


def test_main_reports_unreachable_api(monkeypatch, capsys):
    import requests

    cfg = SimpleNamespace(
        daily_publish=SimpleNamespace(
            enabled=True, api_url="http://127.0.0.1:9", **vars(CFG)
        )
    )
    monkeypatch.setattr("noticiencias.config_manager.load_config", lambda: cfg)

    def refuse(*a, **k):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(dp.AdminClient, "_call", refuse)
    monkeypatch.setattr(dp, "MARKER_DIR", Path("/nonexistent-marker-dir"))
    assert dp.main(["--no-collect"]) == 2
    assert "not reachable" in capsys.readouterr().err


def test_main_reports_hung_api(monkeypatch, capsys, tmp_path):
    import requests

    cfg = SimpleNamespace(
        daily_publish=SimpleNamespace(
            enabled=True, api_url="http://127.0.0.1:8000", **vars(CFG)
        )
    )
    monkeypatch.setattr("noticiencias.config_manager.load_config", lambda: cfg)

    def hang(*a, **k):
        raise requests.ReadTimeout("no answer")

    monkeypatch.setattr(dp.AdminClient, "_call", hang)
    # A real run today leaves a marker in data/; never read it here.
    monkeypatch.setattr(dp, "MARKER_DIR", tmp_path)
    assert dp.main(["--no-collect"]) == 2
    assert "not reachable" in capsys.readouterr().err


def test_main_disabled_does_nothing(monkeypatch, capsys):
    cfg = SimpleNamespace(daily_publish=SimpleNamespace(enabled=False))
    monkeypatch.setattr("noticiencias.config_manager.load_config", lambda: cfg)
    assert dp.main([]) == 0
    assert "disabled" in capsys.readouterr().out
