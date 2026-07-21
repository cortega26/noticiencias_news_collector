from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import List, Literal, NamedTuple

from news_collector.config.settings import get_runtime_config

# --- Data Structures ---


class ActivityEvent(NamedTuple):
    timestamp_str: str  # Original string "YYYY-MM-DD HH:mm:ss"
    timestamp_dt: datetime | None
    level: Literal["INFO", "WARNING", "ERROR", "DEBUG", "CRITICAL"]
    category: str
    message: str
    raw_line: str


# --- Parser Logic ---


class LogParser:
    """Parses log lines based on the configured format."""

    # Regex matching: "{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} | {message}"
    # Example: "2023-10-27 10:00:00 | INFO     | news_collector.main:45 | Starting cycle"
    LOG_PATTERN = re.compile(
        r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| "
        r"(?P<level>[A-Z]+)\s*\| "
        r"(?P<source>[^:]+:\d+) \| "
        r"(?P<message>.*)$"
    )

    @classmethod
    def parse_line(cls, line: str) -> ActivityEvent | None:
        line = line.strip()
        if not line:
            return None

        match = cls.LOG_PATTERN.match(line)
        if not match:
            # Fallback or partial handle? For now, skip non-matching lines (stack traces etc)
            return None

        data = match.groupdict()

        # Parse Timestamp
        try:
            ts_dt = datetime.strptime(data["time"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            ts_dt = None

        # Categorize
        message = data["message"]
        level = data["level"]
        source = data["source"]

        category = cls._infer_category(message, source)

        return ActivityEvent(
            timestamp_str=data["time"],
            timestamp_dt=ts_dt,
            level=level,  # type: ignore
            category=category,
            message=message,
            raw_line=line,
        )

    @staticmethod
    def _infer_category(message: str, source: str) -> str:
        """Heuristic to categorise events."""
        msg_lower = message.lower()
        msg_lower = message.lower()
        # src_lower = source.lower()  # Unused

        if "cycle" in msg_lower or "starting" in msg_lower or "finished" in msg_lower:
            return "Lifecycle"
        if (
            "fetch" in msg_lower
            or "rss" in msg_lower
            or "source" in msg_lower
            or "collect" in msg_lower
        ):
            return "Collection"
        if "score" in msg_lower or "rank" in msg_lower or "scoring" in msg_lower:
            return "Scoring"
        if "publish" in msg_lower or "github" in msg_lower or "pr" in msg_lower:
            return "Publishing"
        if "db" in msg_lower or "database" in msg_lower:
            return "Storage"
        if "error" in msg_lower or "fail" in msg_lower:
            return "System Error"

        return "System"


class EventAggregator:
    """Aggregates similar consecutive events to reduce noise."""

    @staticmethod
    def aggregate(events: List[ActivityEvent]) -> List[ActivityEvent]:
        if not events:
            return []

        aggregated = []
        # Simple Logic: Pass through for now.
        # Advanced Logic Step: If we see 5 "Fetching..." items in a row, group them.
        # Implementation:
        last_event = None
        count_similar = 0

        for event in events:
            if not last_event:
                last_event = event
                count_similar = 1
                continue

            # Check similarity (same category, very similar message prefix?)
            is_fetching = (
                "fetching" in event.message.lower()
                and "fetching" in last_event.message.lower()
            )
            is_saving = (
                "saving" in event.message.lower()
                and "saving" in last_event.message.lower()
            )

            if event.category == last_event.category and (is_fetching or is_saving):
                count_similar += 1
            else:
                # Flush last
                aggregated.append(
                    EventAggregator._finalize_event(last_event, count_similar)
                )
                last_event = event
                count_similar = 1

        if last_event:
            aggregated.append(
                EventAggregator._finalize_event(last_event, count_similar)
            )

        return aggregated

    @staticmethod
    def _finalize_event(event: ActivityEvent, count: int) -> ActivityEvent:
        if count <= 1:
            return event

        # Modify message to indicate grouping
        new_msg = f"{event.message} (and {count-1} similar events)"
        return ActivityEvent(
            timestamp_str=event.timestamp_str,
            timestamp_dt=event.timestamp_dt,
            level=event.level,
            category=event.category,
            message=new_msg,
            raw_line=event.raw_line,
        )


class ActivityMonitor:
    """Main facade for retrieving and formatting activity logs."""

    def __init__(self, log_path: Path | None = None):
        if log_path:
            self.log_path = log_path
        else:
            self.log_path = Path(
                get_runtime_config().logging_config.get(
                    "file_path", "data/logs/collector.log"
                )
            )
            # Ensure absolute path logic mirrors admin_panel or settings
            from news_collector.config.settings import BASE_DIR

            if not self.log_path.is_absolute():
                self.log_path = (BASE_DIR / self.log_path).resolve()

    def get_recent_activity(self, limit: int = 50) -> List[ActivityEvent]:
        if not self.log_path.exists():
            return []

        events = []
        # Read from end of file efficiently?
        # For < 1MB log files, reading all lines is fine.
        # Limit to last N lines.
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                # Simple approach: read simple last N lines
                # Ideally we read more to find 50 *valid* events
                lines = f.readlines()[-200:]  # Read last 200 lines

            for line in lines:
                evt = LogParser.parse_line(line)
                if evt:
                    events.append(evt)

            # Sort desc by time? Or keep chronological?
            # Logs are chronological.

            # Aggregate
            agged = EventAggregator.aggregate(events)

            # Return last `limit`
            return agged[-limit:]
        except Exception:
            return []
