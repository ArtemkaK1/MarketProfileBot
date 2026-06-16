from datetime import datetime
from zoneinfo import ZoneInfo

from market_profile_bot.trade_limiter import DailyTradeLimiter


def test_daily_trade_limiter_allows_one_trade_per_market_day():
    limiter = DailyTradeLimiter()
    tz = ZoneInfo("America/New_York")

    assert limiter.reserve(datetime.fromisoformat("2026-06-10T11:30:00-04:00"), tz)
    assert not limiter.reserve(datetime.fromisoformat("2026-06-10T15:30:00-04:00"), tz)
    assert limiter.reserve(datetime.fromisoformat("2026-06-11T11:30:00-04:00"), tz)
