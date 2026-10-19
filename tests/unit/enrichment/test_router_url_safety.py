"""Router URL-safety tests (plan 141).

The real ``validate_url_safety`` guard is the subject here: only the DNS
boundary and the strategy fetchers are stubbed, so the module stays hermetic
(no live DNS, no network). The parametrised cases prove the guard runs before
*every* fetch strategy, so a future strategy cannot slip past it.
"""

from __future__ import annotations

import socket
from contextlib import contextmanager
from typing import Any, Callable, Iterator
from unittest.mock import MagicMock, patch

import pytest

from news_collector.enrichment.host_pacer import HostPacer
from news_collector.enrichment.router import EnrichmentStrategyRouter

# Public address used for the happy-path DNS stub (same precedent as
# tests/unit/utils/test_security.py).
PUBLIC_IP = "8.8.8.8"

# ``headless`` is spelled ``headless_fallback`` in the router; that is the
# branch that reaches ``HeadlessEnricher.enrich``.
STRATEGY_CONFIGS = {
    "http": {"enrichment_strategy": "http"},
    "headless_fallback": {
        "enrichment_strategy": "headless_fallback",
        "headless_enabled": True,
    },
    "scrapling_http": {"enrichment_strategy": "scrapling_http"},
    "scrapling_stealth": {"enrichment_strategy": "scrapling_stealth"},
}

UNSAFE_URLS = [
    "http://127.0.0.1/admin",  # loopback
    "http://169.254.169.254/latest/meta-data/",  # link-local metadata endpoint
    "file:///etc/passwd",  # non-http scheme
    "http://192.168.1.1/",  # private range
]


def _make_router() -> EnrichmentStrategyRouter:
    """Router with every fetch strategy mocked out (the URL guard is real)."""
    router = EnrichmentStrategyRouter(host_pacer=HostPacer.disabled())
    router.logger = MagicMock()
    router.scholarly = MagicMock()
    router.http = MagicMock()
    router.headless = MagicMock()
    router.scrapling = MagicMock()
    router.scrapling_http = MagicMock()
    return router


@contextmanager
def _router_under_test() -> Iterator[EnrichmentStrategyRouter]:
    """Patch module-level collaborators so only routing/guarding is real."""
    lock_manager = MagicMock()
    lock_manager.get_lock.return_value = None
    optimizer = MagicMock()
    optimizer.get_strategy_hint.return_value = None
    with (
        patch("news_collector.enrichment.router.enrichment_metrics", MagicMock()),
        patch("news_collector.enrichment.router.strategy_lock_manager", lock_manager),
        patch("news_collector.enrichment.router.strategy_optimizer", optimizer),
    ):
        yield _make_router()


@contextmanager
def _public_dns() -> Iterator[None]:
    """Stub the DNS boundary; no test in this module resolves a real host."""
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", (PUBLIC_IP, 0))]):
        yield


def _assert_nothing_fetched(router: EnrichmentStrategyRouter) -> None:
    router.http.enrich.assert_not_called()
    router.headless.enrich.assert_not_called()
    router.scrapling.enrich.assert_not_called()
    router.scrapling_http.enrich.assert_not_called()
    router.scholarly.enrich_url.assert_not_called()


def _http_success(router: EnrichmentStrategyRouter) -> tuple[Any, str]:
    router.http.enrich.return_value = {
        "success": True,
        "content": "A" * 600,
        "raw_content": "<html/>",
    }
    return router.http.enrich, "http"


def _headless_success(router: EnrichmentStrategyRouter) -> tuple[Any, str]:
    router.http.enrich.return_value = {"success": False, "error": "403"}
    router.headless.enrich.return_value = {
        "success": True,
        "content": "A" * 600,
        "raw_content": "<html/>",
        "duration": 0.1,
    }
    return router.headless.enrich, "headless"


def _scrapling_http_success(router: EnrichmentStrategyRouter) -> tuple[Any, str]:
    router.scrapling_http.enrich.return_value = {
        "success": True,
        "content": "A" * 600,
        "raw_content": "<html/>",
        "duration": 0.2,
    }
    return router.scrapling_http.enrich, "scrapling_http"


def _scrapling_stealth_success(router: EnrichmentStrategyRouter) -> tuple[Any, str]:
    router.scrapling.enrich.return_value = {
        "success": True,
        "content": "A" * 600,
        "raw_content": "<html/>",
        "duration": 0.2,
    }
    return router.scrapling.enrich, "scrapling_stealth"


SUCCESS_SETUPS: dict[str, Callable[[EnrichmentStrategyRouter], tuple[Any, str]]] = {
    "http": _http_success,
    "headless_fallback": _headless_success,
    "scrapling_http": _scrapling_http_success,
    "scrapling_stealth": _scrapling_stealth_success,
}


@pytest.mark.parametrize("strategy", sorted(STRATEGY_CONFIGS))
@pytest.mark.parametrize("url", UNSAFE_URLS)
def test_unsafe_url_is_rejected_before_any_fetch(strategy: str, url: str) -> None:
    with _router_under_test() as router:
        result = router.route_enrichment(
            "src", dict(STRATEGY_CONFIGS[strategy]), {"url": url}
        )
        _assert_nothing_fetched(router)
        router.logger.warning.assert_called_once()

    assert result == {
        "success": False,
        "reason": "unsafe_url",
        "strategy_used": "none",
    }


def test_unresolvable_host_fails_closed() -> None:
    with (
        _router_under_test() as router,
        patch("socket.getaddrinfo", side_effect=socket.gaierror("unresolvable")),
    ):
        result = router.route_enrichment(
            "src",
            {"enrichment_strategy": "headless_fallback", "headless_enabled": True},
            {"url": "https://unresolvable.invalid/article"},
        )
        _assert_nothing_fetched(router)

    assert result["success"] is False
    assert result["reason"] == "unsafe_url"
    assert result["strategy_used"] == "none"


@pytest.mark.parametrize("strategy", sorted(SUCCESS_SETUPS))
def test_public_url_still_reaches_the_strategy_fetcher(strategy: str) -> None:
    url = "https://news.example.org/article"
    with _router_under_test() as router, _public_dns():
        fetcher, expected_strategy_used = SUCCESS_SETUPS[strategy](router)
        result = router.route_enrichment(
            "src", dict(STRATEGY_CONFIGS[strategy]), {"url": url}
        )
        fetcher.assert_called_once()
        assert fetcher.call_args.args[0] == url
        router.logger.warning.assert_not_called()

    assert result["success"] is True
    assert result["strategy_used"] == expected_strategy_used
