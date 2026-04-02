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
