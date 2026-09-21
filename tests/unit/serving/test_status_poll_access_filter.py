"""Unit tests for the uvicorn status-poll access filter (log hygiene).

The GUI polls the publish/collect status endpoints every few seconds per
active run; silencing only positively-identified successful polls keeps the
access log readable without hiding errors.
"""

import logging

from news_collector.serving.api import _install_status_poll_access_filter


def _record(path, status):
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, "%s", None, None
    )
    record.args = ("127.0.0.1:1", "GET", path, "HTTP/1.1", status)
    return record


def test_status_poll_filter_silences_only_successful_polls():
    _install_status_poll_access_filter()
    _install_status_poll_access_filter()  # installing twice stays single
    access_log = logging.getLogger("uvicorn.access")
    assert len(access_log.filters) >= 1

    def passes(path, status):
        return all(f.filter(_record(path, status)) for f in access_log.filters)

    try:
        assert passes("/v1/admin/publish/status?run_id=1", 200) is False
        assert passes("/v1/admin/collect/status", 200) is False
        assert passes("/v1/admin/publish/status", 500) is True
        assert passes("/v1/admin/articles", 200) is True
    finally:
        access_log.filters = [
            f
            for f in access_log.filters
            if type(f).__name__ != "_StatusPollAccessFilter"
        ]
