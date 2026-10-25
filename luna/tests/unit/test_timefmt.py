"""Operator-facing time formatting: storage stays UTC, display is Tehran (+03:30)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from luna_core.timefmt import TEHRAN, display_tz, fmt, fmt_clock, to_display

UTC_STAMP = "2026-09-24T09:27:41.931618+00:00"


def test_utc_iso_renders_as_tehran_local_time():
    assert fmt(UTC_STAMP) == "2026-09-24 12:57:41 +03:30"


def test_clock_is_short_local_time():
    assert fmt_clock(UTC_STAMP) == "12:57:41 +03:30"


def test_offset_is_plus_330_no_dst():
    """Iran abolished DST in 1402/2023; a fixed +03:30 is exact."""
    assert TEHRAN.utcoffset(datetime(2026, 1, 15, 12, 0)) == timedelta(hours=3, minutes=30)
    assert TEHRAN.utcoffset(datetime(2026, 7, 15, 12, 0)) == timedelta(hours=3, minutes=30)
    assert fmt(UTC_STAMP).endswith("+03:30")


def test_tehran_stamp_is_not_shifted_again():
    """A string already in +03:30 must display unchanged, not move another 3.5 hours."""
    assert fmt("2026-09-24T12:57:41+03:30") == "2026-09-24 12:57:41 +03:30"


def test_naive_input_is_assumed_local_not_shifted():
    naive = datetime(2026, 9, 24, 12, 57, 41)
    assert fmt(naive) == "2026-09-24 12:57:41 +03:30"


def test_round_trip_preserves_the_instant():
    original = datetime.fromisoformat(UTC_STAMP)
    assert to_display(original).astimezone(timezone.utc) == original


def test_display_tz_is_overridable(monkeypatch):
    monkeypatch.setenv("LUNA_TZ", "+00:00")
    assert fmt(UTC_STAMP) == "2026-09-24 09:27:41 +00:00"
    monkeypatch.setenv("LUNA_TZ", "UTC")
    assert fmt(UTC_STAMP) == "2026-09-24 09:27:41 +00:00"
    # An invalid value falls back to Tehran rather than exploding.
    monkeypatch.setenv("LUNA_TZ", "not-a-zone")
    assert fmt(UTC_STAMP) == "2026-09-24 12:57:41 +03:30"


def test_bad_input_is_safe():
    assert fmt(None) == "?"
    assert fmt("not a timestamp") == "?"
