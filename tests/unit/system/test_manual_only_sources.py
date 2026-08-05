from news_collector.system import NewsCollectorSystem


def test_manual_only_sources_are_skipped_unless_explicitly_requested(monkeypatch):
    monkeypatch.setattr(
        "news_collector.system.ALL_SOURCES",
        {
            "normal_source": {"name": "Normal", "manual_only": False},
            "manual_source": {"name": "Manual", "manual_only": True},
        },
    )

    system = NewsCollectorSystem(skip_initialization=True)

    scheduled_sources = system._get_sources_to_process(None)
    explicit_sources = system._get_sources_to_process(["manual_source"])

    assert list(scheduled_sources.keys()) == ["normal_source"]
    assert list(explicit_sources.keys()) == ["manual_source"]


def test_blacklisted_sources_are_skipped_in_scheduled_runs(monkeypatch):
    monkeypatch.setattr(
        "news_collector.system.ALL_SOURCES",
        {
            "normal_source": {"name": "Normal", "blacklisted": False},
            "dead_source": {
                "name": "Dead feed",
                "blacklisted": True,
                "blacklist_reason": "403 behind Cloudflare challenge",
                "blacklisted_date": "2026-08-04",
            },
        },
    )

    system = NewsCollectorSystem(skip_initialization=True)

    scheduled_sources = system._get_sources_to_process(None)

    assert list(scheduled_sources.keys()) == ["normal_source"]


def test_blacklisted_source_still_selected_when_explicitly_requested(monkeypatch):
    monkeypatch.setattr(
        "news_collector.system.ALL_SOURCES",
        {
            "dead_source": {
                "name": "Dead feed",
                "blacklisted": True,
                "blacklist_reason": "403 behind Cloudflare challenge",
                "blacklisted_date": "2026-08-04",
            },
        },
    )

    system = NewsCollectorSystem(skip_initialization=True)

    explicit_sources = system._get_sources_to_process(["dead_source"])

    assert list(explicit_sources.keys()) == ["dead_source"]
