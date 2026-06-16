from datetime import datetime
from zoneinfo import ZoneInfo

from market_profile_bot.risk import is_entry_allowed


def test_entry_before_market_cutoff_is_allowed():
    tz = ZoneInfo("America/New_York")
    assert is_entry_allowed(datetime.fromisoformat("2026-06-10T15:59:00-04:00"), tz)


def test_entry_at_market_cutoff_is_rejected():
    tz = ZoneInfo("America/New_York")
    assert not is_entry_allowed(datetime.fromisoformat("2026-06-10T16:00:00-04:00"), tz)


def test_weekend_entry_is_rejected():
    tz = ZoneInfo("America/New_York")
    assert not is_entry_allowed(datetime.fromisoformat("2026-06-13T12:00:00-04:00"), tz)
