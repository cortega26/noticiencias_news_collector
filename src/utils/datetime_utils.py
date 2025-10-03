from __future__ import annotations

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
        dt = datetime.fromtimestamp(_time.mktime(value), tz=timezone.utc)
    else:
        # string or other
        dt = date_parser.parse(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

    tz_offset = _tz_offset_minutes(dt)
    tzname = _tz_name(dt)
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc, tz_offset, tzname


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
