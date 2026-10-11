from __future__ import annotations

import calendar
import time as _time
from datetime import datetime, timedelta, timezone
from typing import Tuple, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil import parser as date_parser


def _tz_offset_minutes(dt: datetime) -> int:
    if dt.tzinfo is None:
        return 0
    offset = dt.utcoffset() or timedelta(0)
    return int(offset.total_seconds() // 60)


def _tz_name(dt: datetime) -> str:
    if dt.tzinfo is None:
        return "UTC"
    name = dt.tzname() or ""
    if name:
        return name
    # Fallback to offset label
    minutes = _tz_offset_minutes(dt)
    sign = "+" if minutes >= 0 else "-"
    m = abs(minutes)
    return f"UTC{sign}{m // 60:02d}:{m % 60:02d}"


def parse_to_utc_with_tzinfo(
    value: Union[str, _time.struct_time, datetime, None],
) -> Tuple[datetime, int, str]:
    """
    Parse many feed date forms into canonical UTC datetime and capture original tz info.

    Returns: (dt_utc, original_tz_offset_minutes, original_tz_name)
    """
    if value is None:
        dt = datetime.now(timezone.utc)
        return dt, 0, "UTC"

    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, _time.struct_time):
        # calendar.timegm interprets struct_time as UTC (feed dates are
        # expressed in UTC); mktime used the host's local timezone, which
        # produced host-timezone-dependent timestamps and overflows pre-2038.
        dt = datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)
    else:
        # string or other
        dt = date_parser.parse(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

    tz_offset = _tz_offset_minutes(dt)
    tzname = _tz_name(dt)
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc, tz_offset, tzname


def assume_utc(dt: datetime, *, source_id: str = "") -> datetime:
    """Normalize a feed timestamp to an aware UTC datetime.

    Single explicit assumption point for naive feed timestamps (plan 120):
    feeds rarely declare a zone, so a naive datetime is ASSUMED to be UTC
    and labeled as such. Aware datetimes are converted to UTC, preserving
    the instant.

    A datetime cannot carry provenance, so callers that build a
    ``CollectorArticleModel`` from a naive input must record the assumption
    via the existing model fields (``published_tz_offset_minutes=0``,
    ``published_tz_name="UTC (assumed)"``).

    A source known to publish in a non-UTC zone needs explicit per-source
    handling (future work, not here); ``source_id`` names the source for
    that future mapping and for log context.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_display_tz(dt_utc: datetime, tz: str = "America/Santiago") -> datetime:
    """Convert a UTC datetime to the given display timezone (zoneinfo key)."""
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    try:
        return dt_utc.astimezone(ZoneInfo(tz))
    except ZoneInfoNotFoundError:
        return dt_utc


def format_display(
    dt_utc: datetime, tz: str = "America/Santiago", fmt: str = "%Y-%m-%d %H:%M:%S %Z%z"
) -> str:
    """Format a UTC datetime for display in the requested timezone."""
    return to_display_tz(dt_utc, tz).strftime(fmt)
