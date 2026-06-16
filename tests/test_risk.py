from datetime import datetime
from zoneinfo import ZoneInfo

from market_profile_bot.risk import is_entry_allowed


def test_entry_before_xetra_close_is_allowed():
    tz = ZoneInfo("Europe/Berlin")
    assert is_entry_allowed(datetime.fromisoformat("2026-06-10T17:29:00+02:00"), tz)


def test_entry_at_xetra_close_is_rejected():
    tz = ZoneInfo("Europe/Berlin")
    assert not is_entry_allowed(datetime.fromisoformat("2026-06-10T17:30:00+02:00"), tz)


def test_weekend_entry_is_rejected():
    tz = ZoneInfo("Europe/Berlin")
    assert not is_entry_allowed(datetime.fromisoformat("2026-06-13T12:00:00+02:00"), tz)
