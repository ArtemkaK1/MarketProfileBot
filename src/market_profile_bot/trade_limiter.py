from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


class DailyTradeLimiter:
    def __init__(self) -> None:
        self._trade_dates: set[date] = set()

    def reserve(self, alert_time: datetime, market_tz: ZoneInfo) -> bool:
        trade_date = alert_time.astimezone(market_tz).date()
        if trade_date in self._trade_dates:
            return False
        self._trade_dates.add(trade_date)
        return True
