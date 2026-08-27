"""Fail-safe scheduling helpers shared by startup and periodic reconciliation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def persisted_run_time(value: str | None, now: datetime) -> datetime | None:
    """Parse a stored UTC run time without allowing it to suppress recovery.

    Naive, malformed, or implausibly future values are untrusted.  A small
    future tolerance accommodates ordinary wall-clock correction between
    shutdown and startup.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        parsed = parsed.astimezone(timezone.utc)
        return parsed if parsed <= now.astimezone(timezone.utc) + timedelta(minutes=5) else None
    except (TypeError, ValueError, OverflowError):
        return None
