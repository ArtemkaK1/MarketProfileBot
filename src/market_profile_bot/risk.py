from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo


XETRA_ENTRY_CUTOFF = time(17, 30)


def is_entry_allowed(alert_time: datetime, market_tz: ZoneInfo) -> bool:
    market_time = alert_time.astimezone(market_tz)
    if market_time.weekday() >= 5:
        return False
    return market_time.time() < XETRA_ENTRY_CUTOFF
