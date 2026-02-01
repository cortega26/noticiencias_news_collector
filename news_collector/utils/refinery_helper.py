from typing import Any, List, Optional


def has_no_activity(events: Optional[List[Any]]) -> bool:
    """
    Checks if the events list is empty or None.

    Args:
        events: A list of activity events or None.

    Returns:
        True if events is None or empty, False otherwise.
    """
    if events is None:
        return True
    if not isinstance(events, list):
        return not events
    return len(events) == 0
