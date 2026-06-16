from __future__ import annotations

from collections import OrderedDict


class AlertDeduplicator:
    def __init__(self, max_size: int = 1000) -> None:
        self._max_size = max_size
        self._seen: OrderedDict[str, None] = OrderedDict()

    def seen(self, alert_id: str) -> bool:
        if alert_id in self._seen:
            self._seen.move_to_end(alert_id)
            return True
        self._seen[alert_id] = None
        if len(self._seen) > self._max_size:
            self._seen.popitem(last=False)
        return False

