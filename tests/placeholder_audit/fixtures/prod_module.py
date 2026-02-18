"""Fixture module for placeholder audit tests."""


class Example:
    """Example class."""

    def action(self) -> None:
        """Perform action."""
        value = 1
        # TODO[owner=@alice; issue=#123]: add retries for unstable network
        return None if value else None
