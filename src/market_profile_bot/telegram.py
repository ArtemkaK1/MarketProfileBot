from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from urllib import parse, request

from .config import Settings
from .execution import ExecutionResult
from .models import AlertType, Direction, TradingViewAlert

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelegramNotifier:
    bot_token: str | None
    chat_id: str | None
    enabled: bool = False
    timeout: float = 5.0

    @classmethod
    def from_settings(cls, settings: Settings) -> "TelegramNotifier":
        return cls(
            bot_token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id,
            enabled=settings.telegram_enabled,
        )

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.bot_token and self.chat_id)

    def send(self, text: str) -> None:
        if not self.configured:
            return

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        body = parse.urlencode(
            {
                "chat_id": self.chat_id,
                "text": text,
                "disable_web_page_preview": "true",
            }
        ).encode()
        req = request.Request(url, data=body, method="POST")

        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if not payload.get("ok"):
                    logger.warning("Telegram sendMessage failed: %s", payload)
        except Exception:
            logger.exception("Telegram notification failed")

    def signal_received(self, alert: TradingViewAlert) -> None:
        self.send(format_signal_message(alert))

    def bot_started(self, *, backend: str, dry_run: bool, auto_trade: bool) -> None:
        self.send(
            "Bot is active\n"
            f"Backend: {backend}\n"
            f"DRY_RUN: {dry_run}\n"
            f"AUTO_TRADE: {auto_trade}"
        )

    def signal_rejected(self, alert: TradingViewAlert, reason: str) -> None:
        self.send(f"{format_signal_message(alert)}\nStatus: rejected\nReason: {reason}")

    def signal_skipped(self, alert: TradingViewAlert, reason: str) -> None:
        self.send(f"{format_signal_message(alert)}\nStatus: skipped\nReason: {reason}")

    def execution_result(self, alert: TradingViewAlert, result: ExecutionResult) -> None:
        order = f"\nOrder ID: {result.order_id}" if result.order_id is not None else ""
        self.send(f"{format_signal_message(alert)}\nStatus: {result.status}\nDetail: {result.detail}{order}")


def format_signal_message(alert: TradingViewAlert) -> str:
    local_time = alert.time.isoformat()
    if alert.type == AlertType.IB_READY:
        return (
            "TradingView signal: IB_READY\n"
            f"Symbol: {alert.symbol}\n"
            f"Time: {local_time}\n"
            f"IB High: {alert.ib_high}\n"
            f"IB Low: {alert.ib_low}\n"
            f"IB 0.5: {alert.ib_mid}\n"
            f"ID: {alert.id}"
        )

    direction = "LONG" if alert.direction == Direction.LONG else "SHORT"
    return (
        f"TradingView signal: {alert.type} {direction}\n"
        f"Symbol: {alert.symbol}\n"
        f"Time: {local_time}\n"
        f"Price: {alert.price}\n"
        f"SL: {alert.sl}\n"
        f"TP: {alert.tp}\n"
        f"Risk: {alert.risk_percent}%\n"
        f"RR: {alert.rr}\n"
        f"IB High: {alert.ib_high}\n"
        f"IB Low: {alert.ib_low}\n"
        f"IB 0.5: {alert.ib_mid}\n"
        f"ID: {alert.id}"
    )
