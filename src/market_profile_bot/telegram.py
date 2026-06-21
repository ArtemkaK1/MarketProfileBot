from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from urllib import parse, request

from .config import Settings
from .bingx_executor import BingXAccountState
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

    def send(self, text: str, *, chat_id: str | None = None) -> None:
        if not self.configured:
            return

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        body = parse.urlencode(
            {
                "chat_id": chat_id or self.chat_id,
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

    def set_webhook(self, webhook_url: str) -> bool:
        if not self.configured:
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/setWebhook"
        body = parse.urlencode(
            {
                "url": webhook_url,
                "allowed_updates": json.dumps(["message", "edited_message"]),
            }
        ).encode()
        req = request.Request(url, data=body, method="POST")
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if payload.get("ok"):
                    logger.info("Telegram webhook registered: %s", webhook_url)
                    return True
                logger.error("Telegram setWebhook failed: %s", payload)
        except Exception:
            logger.exception("Telegram webhook registration failed")
        return False

    def signal_received(self, alert: TradingViewAlert) -> None:
        self.send(format_signal_message(alert))

    def bot_started(self, *, backend: str, dry_run: bool, auto_trade: bool) -> None:
        self.send(
            "🟢 Bot started\n\n"
            f"Exchange: {backend.title()}\n"
            f"Execution: {'Simulation' if dry_run else 'Live'}\n"
            f"Auto-trading: {_on_off(auto_trade)}\n\n"
            "Use /state to check the futures account."
        )

    def signal_rejected(self, alert: TradingViewAlert, reason: str) -> None:
        self.send(f"{format_signal_message(alert)}\n\n❌ Rejected\n{_friendly_reason(reason)}")

    def signal_skipped(self, alert: TradingViewAlert, reason: str) -> None:
        self.send(f"{format_signal_message(alert)}\n\n⏸ Skipped\n{_friendly_reason(reason)}")

    def execution_result(self, alert: TradingViewAlert, result: ExecutionResult) -> None:
        order = f"\nOrder ID: {result.order_id}" if result.order_id is not None else ""
        status_icon = "✅" if result.status == "filled" else "🧪" if result.status == "dry_run" else "ℹ️"
        self.send(
            f"{format_signal_message(alert)}\n\n"
            f"{status_icon} {_humanize(result.status)}\n"
            f"{result.detail}{order}"
        )

    def account_state(self, state: BingXAccountState, *, chat_id: str | None = None) -> None:
        self.send(format_account_state_message(state), chat_id=chat_id)

    def command_error(self, detail: str, *, chat_id: str | None = None) -> None:
        self.send(f"⚠️ Could not load BingX account state\n\n{detail}", chat_id=chat_id)


def format_signal_message(alert: TradingViewAlert) -> str:
    local_time = alert.time.isoformat()
    if alert.type == AlertType.IB_READY:
        return (
            "📊 Initial balance is ready\n\n"
            f"Symbol: {alert.symbol}\n"
            f"Time: {local_time}\n"
            f"High: {alert.ib_high}\n"
            f"Midpoint: {alert.ib_mid}\n"
            f"Low: {alert.ib_low}\n\n"
            f"Signal ID: {alert.id}"
        )

    direction = "LONG" if alert.direction == Direction.LONG else "SHORT"
    return (
        f"🔔 {alert.type.value.title()} signal · {direction}\n\n"
        f"Symbol: {alert.symbol}\n"
        f"Time: {local_time}\n"
        f"Entry: {alert.price}\n"
        f"Stop loss: {alert.sl}\n"
        f"Take profit: {alert.tp}\n"
        f"Risk: {alert.risk_percent}% · R:R {alert.rr}\n\n"
        f"IB range: {alert.ib_low} — {alert.ib_high}\n"
        f"IB midpoint: {alert.ib_mid}\n\n"
        f"Signal ID: {alert.id}"
    )


def format_account_state_message(state: BingXAccountState) -> str:
    leverage = (
        f"{_decimal_text(state.long_leverage)}x"
        if state.long_leverage == state.short_leverage
        else (
            f"Long {_decimal_text(state.long_leverage)}x · "
            f"Short {_decimal_text(state.short_leverage)}x"
        )
    )
    available = (
        f"\nAvailable margin: {_decimal_text(state.available_margin)} USDT"
        if state.available_margin is not None
        else ""
    )
    margin_type = {
        "CROSSED": "Cross",
        "CROSS": "Cross",
        "ISOLATED": "Isolated",
    }.get(state.margin_type.upper(), _humanize(state.margin_type))
    return (
        "💰 BingX USDT Futures\n\n"
        f"Balance: {_decimal_text(state.balance)} USDT{available}\n"
        f"Symbol: {state.symbol}\n"
        f"Margin: {margin_type}\n"
        f"Leverage: {leverage}"
    )


def _decimal_text(value) -> str:
    return format(value.normalize(), "f")


def _humanize(value: str) -> str:
    return value.replace("_", " ").strip().title()


def _on_off(enabled: bool) -> str:
    return "On" if enabled else "Off"


def _friendly_reason(reason: str) -> str:
    reasons = {
        "outside_entry_window": "The signal arrived outside the configured entry window.",
        "auto_trade_disabled": "Auto-trading is currently turned off.",
        "daily_trade_limit_reached": "The daily trade limit has already been reached.",
    }
    return reasons.get(reason, _humanize(reason))
