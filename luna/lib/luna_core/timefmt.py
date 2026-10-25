"""Time formatting for operator-facing output (logs, CLI, replay reports).

Storage stays timezone-aware UTC — that is what makes the freshness/timeliness gates correct and
comparable. Only *display* converts to the operator's local zone, so timestamps read as Tehran time
(+03:30) instead of raw UTC.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

# Iran Standard Time. Fixed +03:30 with no DST since 1402/2023; a fixed offset is exact and avoids a
# tzdata dependency in the slim runtime.
TEHRAN = timezone(timedelta(hours=3, minutes=30), "Asia/Tehran")


def display_tz() -> timezone:
    """The display zone, overridable via ``LUNA_TZ`` (an IANA name or a ``+HH:MM`` offset)."""
    raw = str(os.getenv("LUNA_TZ", "") or "").strip()
    if not raw:
        return TEHRAN
    if raw.startswith(("+", "-")):
        try:
            sign = 1 if raw[0] == "+" else -1
            hours, _, minutes = raw[1:].partition(":")
            return timezone(sign * timedelta(hours=int(hours), minutes=int(minutes or 0)), raw)
        except (TypeError, ValueError):
            return TEHRAN
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(raw)
    except Exception:
        return TEHRAN


def to_display(value) -> Optional[datetime]:
    """Normalize a datetime or ISO-8601 string into the display zone.

    Naive input is assumed to already be in the display zone (never silently shifted).
    """
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=display_tz())
    return value.astimezone(display_tz())


def fmt(value, *, fmt: str = "%Y-%m-%d %H:%M:%S", with_tz: bool = True) -> str:
    """Render a datetime/ISO string in the display zone, e.g. ``2026-09-24 13:27:41 +03:30``."""
    local = to_display(value)
    if local is None:
        return "?"
    text = local.strftime(fmt)
    if not with_tz:
        return text
    offset = local.utcoffset() or timedelta(0)
    total = int(offset.total_seconds())
    sign = "+" if total >= 0 else "-"
    hours, rem = divmod(abs(total), 3600)
    minutes = rem // 60
    return f"{text} {sign}{hours:02d}:{minutes:02d}"


def fmt_clock(value) -> str:
    """Short local time, e.g. ``13:27:41 +03:30``."""
    return fmt(value, fmt="%H:%M:%S")
