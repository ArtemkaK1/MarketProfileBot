from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo


DEFAULT_ENTRY_CUTOFF = time(16, 0)


def is_entry_allowed(
    alert_time: datetime,
    market_tz: ZoneInfo,
    entry_cutoff: time = DEFAULT_ENTRY_CUTOFF,
) -> bool:
    market_time = alert_time.astimezone(market_tz)
    if market_time.weekday() >= 5:
        return False
    return market_time.time() < entry_cutoff
