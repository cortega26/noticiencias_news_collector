from datetime import datetime, timezone

import pytest
from src.utils.datetime_utils import (
    parse_to_utc_with_tzinfo,
    to_display_tz,
    format_display,
)


def test_parse_various_tz_strings():
    # GMT string
    dt, off, name = parse_to_utc_with_tzinfo("Tue, 15 Jan 2019 12:45:26 GMT")
    assert dt.tzinfo is not None and dt.tzinfo == timezone.utc
    assert off == 0
    assert name.upper().startswith("GMT") or name.upper() == "UTC"

    # ISO with offset -0300
    dt2, off2, name2 = parse_to_utc_with_tzinfo("2025-09-30T12:00:00-03:00")
    assert off2 == -180
    assert (dt2 - dt2.astimezone(timezone.utc)).total_seconds() == 0

    # Naive -> treated as UTC
    dt3, off3, _ = parse_to_utc_with_tzinfo("2024-01-01 00:00:00")
    assert off3 == 0
    assert dt3.tzinfo == timezone.utc


def test_display_santiago_format():
    base = datetime(2025, 9, 1, 15, 0, tzinfo=timezone.utc)
    local = to_display_tz(base, "America/Santiago")
    if local.tzinfo is timezone.utc:
        pytest.skip("ZoneInfo data for America/Santiago not available")
    assert local.tzinfo is not None
    s = format_display(base, "America/Santiago")
    assert "America" not in s
