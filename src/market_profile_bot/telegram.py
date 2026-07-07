from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from urllib import parse, request

from .config import Settings
from .execution import ExecutionResult
from .models import AlertType, Direction, TradingViewAlert
from .trading import AccountState, adjust_trade_levels

logger = logging.getLogger(__name__)


TELEGRAM_COMMANDS = [
    ("vanta_state", "VantaTrading account state"),
    ("vanta_test_position", "Dry-run Vanta position: LONG|SHORT ENTRY SL TP"),
    ("bingx_state", "BingX account state"),
    ("bingx_test_position", "Dry-run BingX position: LONG|SHORT ENTRY SL TP"),
]


@dataclass(frozen=True)
class TelegramNotifier:
    bot_token: str | None
    chat_id: str | None
    enabled: bool = False
    risk_percent: float | None = None
    sl_tp_offset_points: float = 0.0
    timeout: float = 5.0

    @classmethod
    def from_settings(cls, settings: Settings) -> "TelegramNotifier":
        return cls(
            bot_token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id,
            enabled=settings.telegram_enabled,
            risk_percent=settings.risk_percent,
            sl_tp_offset_points=settings.sl_tp_offset_points,
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

    def set_commands(self) -> bool:
        if not self.configured:
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/setMyCommands"
        body = parse.urlencode(
            {
                "commands": json.dumps(
                    [
                        {"command": command, "description": description}
                        for command, description in TELEGRAM_COMMANDS
                    ]
                ),
            }
        ).encode()
        req = request.Request(url, data=body, method="POST")
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if payload.get("ok"):
                    logger.info("Telegram commands registered")
                    return True
                logger.error("Telegram setMyCommands failed: %s", payload)
        except Exception:
            logger.exception("Telegram command registration failed")
        return False

    def signal_received(self, alert: TradingViewAlert) -> None:
        self.send(
            format_signal_message(
                alert,
                risk_percent=self.risk_percent,
                sl_tp_offset_points=self.sl_tp_offset_points,
            )
        )

    def bot_started(self, *, backend: str, dry_run: bool, auto_trade: bool) -> None:
        self.send(
            "🟢 Bot started\n\n"
            f"Exchange: {backend.title()}\n"
            f"Execution: {'Simulation' if dry_run else 'Live'}\n"
            f"Auto-trading: {_on_off(auto_trade)}\n\n"
            "Commands: /vanta_state, /vanta_test_position, /bingx_state, /bingx_test_position"
        )

    def signal_rejected(self, alert: TradingViewAlert, reason: str) -> None:
        self.send(
            f"{format_signal_message(alert, risk_percent=self.risk_percent, sl_tp_offset_points=self.sl_tp_offset_points)}"
            f"\n\n❌ Rejected\n{_friendly_reason(reason)}"
        )

    def signal_skipped(self, alert: TradingViewAlert, reason: str) -> None:
        self.send(
            f"{format_signal_message(alert, risk_percent=self.risk_percent, sl_tp_offset_points=self.sl_tp_offset_points)}"
            f"\n\n⏸ Skipped\n{_friendly_reason(reason)}"
        )

    def execution_result(self, alert: TradingViewAlert, result: ExecutionResult) -> None:
        order = f"\nOrder ID: {result.order_id}" if result.order_id is not None else ""
        status_icon = "✅" if result.status == "filled" else "🧪" if result.status == "dry_run" else "ℹ️"
        self.send(
            f"{format_signal_message(alert, risk_percent=self.risk_percent, sl_tp_offset_points=self.sl_tp_offset_points)}\n\n"
            f"{status_icon} {_humanize(result.status)}\n"
            f"{result.detail}{order}"
        )

    def execution_failed(self, alert: TradingViewAlert, detail: str) -> None:
        self.send(
            f"{format_signal_message(alert, risk_percent=self.risk_percent, sl_tp_offset_points=self.sl_tp_offset_points)}\n\n"
            f"⚠️ Order not placed\n{detail}"
        )

    def account_state(self, state: AccountState, *, chat_id: str | None = None) -> None:
        self.send(format_account_state_message(state), chat_id=chat_id)

    def command_error(
        self,
        detail: str,
        *,
        chat_id: str | None = None,
        title: str = "Could not load account state",
    ) -> None:
        self.send(f"⚠️ {title}\n\n{detail}", chat_id=chat_id)


def format_signal_message(
    alert: TradingViewAlert,
    *,
    risk_percent: float | None = None,
    sl_tp_offset_points: float = 0.0,
) -> str:
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
    effective_risk = alert.risk_percent if risk_percent is None else risk_percent
    effective_alert = adjust_trade_levels(alert, sl_tp_offset_points)
    return (
        f"🔔 {alert.type.value.title()} signal · {direction}\n\n"
        f"Symbol: {alert.symbol}\n"
        f"Time: {local_time}\n"
        f"Entry: {alert.price}\n"
        f"Stop loss: {effective_alert.sl}\n"
        f"Take profit: {effective_alert.tp}\n"
        f"Bot risk: {_number_text(effective_risk)}% · R:R {alert.rr}\n\n"
        f"IB range: {alert.ib_low} — {alert.ib_high}\n"
        f"IB midpoint: {alert.ib_mid}\n\n"
        f"Signal ID: {alert.id}"
    )


def format_account_state_message(state: AccountState) -> str:
    available = (
        f"\nAvailable margin: {_decimal_text(state.available_margin)} {state.currency}"
        if state.available_margin is not None
        else ""
    )
    buying_power = (
        f"\nBuying power: {_decimal_text(state.buying_power)} {state.currency}"
        if state.buying_power is not None
        else ""
    )
    leverage = (
        f"\nLeverage: {_decimal_text(state.leverage)}x"
        if state.leverage is not None
        else ""
    )
    if state.long_leverage is not None and state.short_leverage is not None:
        leverage = (
            f"\nLeverage: {_decimal_text(state.long_leverage)}x"
            if state.long_leverage == state.short_leverage
            else (
                f"\nLeverage: Long {_decimal_text(state.long_leverage)}x · "
                f"Short {_decimal_text(state.short_leverage)}x"
            )
        )
    margin = (
        f"\nMargin: {_margin_text(state.margin_type)}"
        if state.margin_type is not None
        else ""
    )
    return (
        f"💰 {state.platform}\n\n"
        f"Balance: {_decimal_text(state.balance)} {state.currency}"
        f"{available}{buying_power}{margin}{leverage}\n"
        f"Symbol: {state.symbol}"
    )


def _decimal_text(value) -> str:
    return format(value.normalize(), "f")


def _number_text(value: float) -> str:
    return format(value, "g")


def _humanize(value: str) -> str:
    return value.replace("_", " ").strip().title()


def _margin_text(value: str) -> str:
    return {
        "CROSSED": "Cross",
        "CROSS": "Cross",
        "ISOLATED": "Isolated",
    }.get(value.upper(), _humanize(value))


def _on_off(enabled: bool) -> str:
    return "On" if enabled else "Off"


def _friendly_reason(reason: str) -> str:
    reasons = {
        "outside_entry_window": "The signal arrived outside the configured entry window.",
        "auto_trade_disabled": "Auto-trading is currently turned off.",
        "daily_trade_limit_reached": "The daily trade limit has already been reached.",
    }
    return reasons.get(reason, _humanize(reason))
