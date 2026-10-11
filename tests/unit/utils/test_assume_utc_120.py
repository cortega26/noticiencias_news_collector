"""Plan 120 Step 2: one explicit UTC-assumption point (assume_utc).

Locks in:
- naive datetimes are labeled UTC (assumption, not host-local inference);
- aware datetimes convert to UTC preserving the instant;
- normalization is host-timezone independent (run this file with
  TZ=Pacific/Kiritimati and TZ=America/New_York to prove it);
- model-building callers record the assumption via the existing provenance
  fields (offset 0 / "UTC (assumed)").
"""

import email.utils
from datetime import datetime, timedelta, timezone

from news_collector.collectors.admission import is_too_old
from news_collector.contracts import CollectorArticleModel
from news_collector.utils.datetime_utils import assume_utc

NAIVE = datetime(2026, 3, 15, 12, 0, 0)


def test_naive_is_labeled_utc_unchanged_wall_time():
    out = assume_utc(NAIVE)
    assert out.tzinfo == timezone.utc
    assert out.replace(tzinfo=None) == NAIVE


def test_naive_result_is_host_tz_independent():
    """Must hold under ANY host TZ (CI runs this file with two TZ values).

    A host-dependent implementation (mktime/local fromtimestamp) would shift
    the instant; labeling UTC keeps the exact wall time in UTC.
    """
    out = assume_utc(NAIVE)
    assert out == datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
    assert out.utcoffset() == timedelta(0)


def test_aware_non_utc_converts_preserving_instant():
    # UTC-5 wall time 07:00 == 12:00 UTC.
    aware = datetime(2026, 3, 15, 7, 0, 0, tzinfo=timezone(-timedelta(hours=5)))
    out = assume_utc(aware)
    assert out == datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
    assert out.tzinfo == timezone.utc


def test_already_utc_passes_through():
    aware_utc = datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
    assert assume_utc(aware_utc) == aware_utc


def test_retry_after_style_naive_parsed_date_assumed_utc():
    """email.utils.parsedate_to_datetime without a zone -> assumed UTC."""
    parsed = email.utils.parsedate_to_datetime("Sun, 15 Mar 2026 12:00:00")
    assert parsed is not None and parsed.tzinfo is None
    out = assume_utc(parsed)
    assert out == datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)


def test_admission_treats_naive_as_utc():
    now = datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc)
    # 40 days old as naive wall time == 40 days old in UTC -> too old.
    assert is_too_old(datetime(2026, 3, 11, 12, 0, 0), 30, now) is True
    # 2 days old -> not too old.
    assert is_too_old(datetime(2026, 4, 18, 12, 0, 0), 30, now) is False


def test_model_caller_records_assumption_in_provenance_fields():
    """Callers building a model from a naive dt record offset 0 / name."""
    normalized = assume_utc(NAIVE, source_id="test_source")
    article = CollectorArticleModel(
        url="https://example.com/assumed-utc",
        title="A sufficiently long assumed-utc headline",
        summary="",
        content="x" * 600,
        source_id="test_source",
        source_name="Test Source",
        category="science",
        published_date=normalized,
        published_tz_offset_minutes=0,
        published_tz_name="UTC (assumed)",
    )
    assert article.published_date == datetime(
        2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc
    )
    assert article.published_tz_offset_minutes == 0
    assert article.published_tz_name == "UTC (assumed)"
