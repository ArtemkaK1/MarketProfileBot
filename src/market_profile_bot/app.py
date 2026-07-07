from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime

from fastapi import FastAPI, HTTPException

from .config import Settings
from .dedupe import AlertDeduplicator
from .models import AlertType, Direction, TradingViewAlert
from .platforms.bingx import BingXExecutor
from .platforms.vanta_trading import VantaTradingExecutor
from .risk import is_entry_allowed
from .telegram import TelegramNotifier
from .trade_limiter import DailyTradeLimiter
from .trading import TradingExecutor

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    executor = _create_executor(settings)
    dedupe = AlertDeduplicator()
    trade_limiter = DailyTradeLimiter()
    notifier = TelegramNotifier.from_settings(settings)

    app = FastAPI(title="NASDAQ Pre-NYSE IB Trading Bot")

    @app.on_event("startup")
    def notify_startup():
        webhook_url = settings.telegram_webhook_url
        if webhook_url:
            notifier.set_webhook(webhook_url)
        elif notifier.configured:
            logger.warning(
                "Telegram commands are disabled: set TELEGRAM_WEBHOOK_URL or "
                "RAILWAY_PUBLIC_DOMAIN"
            )
        notifier.set_commands()
        notifier.bot_started(
            backend=executor.platform_name,
            dry_run=settings.dry_run,
            auto_trade=settings.auto_trade,
        )

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "backend": executor.platform_name,
            "dry_run": settings.dry_run,
            "auto_trade": settings.auto_trade,
        }

    @app.post("/telegram/webhook")
    def telegram_webhook(update: dict):
        message = update.get("message") or update.get("edited_message") or {}
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = str(message.get("text", "")).strip()
        parts = text.split()
        command = parts[0].split("@", 1)[0] if parts else ""

        if not notifier.configured or chat_id != str(settings.telegram_chat_id):
            return {"status": "ignored"}

        state_platform = _state_command_platform(command)
        if state_platform is not None:
            try:
                command_settings = replace(settings, trading_platform=state_platform)
                command_executor = _create_executor(command_settings)
                notifier.account_state(command_executor.current_state(), chat_id=chat_id)
            except RuntimeError as exc:
                logger.exception("Could not retrieve account state")
                notifier.command_error(str(exc), chat_id=chat_id)
            return {"status": "ok"}

        test_platform = _test_position_command_platform(command)
        if test_platform is not None:
            try:
                command_settings = replace(
                    settings, trading_platform=test_platform, dry_run=True
                )
                test_alert = _test_position_alert(parts[1:], command_settings)
                dry_run_executor = _create_executor(command_settings)
                result = dry_run_executor.execute(test_alert)
                notifier.execution_result(test_alert, result)
                return {"status": result.status, "detail": result.detail}
            except (RuntimeError, ValueError) as exc:
                logger.exception("Could not run test position command")
                notifier.command_error(
                    str(exc), chat_id=chat_id, title="Could not run test position"
                )
                return {"status": "error", "reason": str(exc)}

        return {"status": "ignored"}

    @app.post("/webhook/tradingview")
    def tradingview_webhook(alert: TradingViewAlert):
        if not settings.webhook_secret:
            raise HTTPException(status_code=500, detail="WEBHOOK_SECRET is not configured")
        if alert.secret != settings.webhook_secret:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")
        if dedupe.seen(alert.id):
            return {"status": "duplicate", "id": alert.id}

        logger.info("Received alert %s %s %s", alert.type, alert.direction, alert.id)

        if alert.type == AlertType.IB_READY:
            notifier.signal_received(alert)
            return {
                "status": "ib_ready",
                "ib_high": alert.ib_high,
                "ib_low": alert.ib_low,
                "ib_mid": alert.ib_mid,
            }

        if not is_entry_allowed(alert.time, settings.timezone, settings.entry_cutoff):
            reason = "outside_entry_window"
            notifier.signal_rejected(alert, reason)
            return {"status": "rejected", "reason": reason}

        if not settings.auto_trade:
            notifier.signal_skipped(alert, "auto_trade_disabled")
            return {"status": "signal_received", "auto_trade": False, "id": alert.id}

        if not trade_limiter.reserve(alert.time, settings.timezone):
            reason = "daily_trade_limit_reached"
            notifier.signal_rejected(alert, reason)
            return {"status": "rejected", "reason": reason}

        try:
            result = executor.execute(alert)
        except RuntimeError as exc:
            logger.exception("Execution failed for alert %s", alert.id)
            notifier.execution_failed(alert, str(exc))
            return {"status": "error", "reason": str(exc), "id": alert.id}
        notifier.execution_result(alert, result)
        return {"status": result.status, "detail": result.detail, "order_id": result.order_id}

    return app


def _create_executor(settings: Settings) -> TradingExecutor:
    platform = settings.trading_platform.strip().lower()
    if platform == "vanta_trading":
        return VantaTradingExecutor(settings)
    if platform == "bingx":
        return BingXExecutor(settings)
    raise RuntimeError(f"Unsupported TRADING_PLATFORM={settings.trading_platform!r}")


def _state_command_platform(command: str) -> str | None:
    return {
        "/vanta_state": "vanta_trading",
        "/bingx_state": "bingx",
    }.get(command)


def _test_position_command_platform(command: str) -> str | None:
    return {
        "/vanta_test_position": "vanta_trading",
        "/bingx_test_position": "bingx",
    }.get(command)


def _test_position_alert(args: list[str], settings: Settings) -> TradingViewAlert:
    if len(args) != 4:
        raise ValueError("Usage: /vanta_test_position or /bingx_test_position LONG|SHORT ENTRY SL TP")
    direction = Direction(args[0].upper())
    price = float(args[1])
    sl = float(args[2])
    tp = float(args[3])
    ib_low = min(price, sl, tp)
    ib_high = max(price, sl, tp)
    stop_distance = abs(price - sl)
    if stop_distance <= 0:
        raise ValueError("SL must be different from entry")
    rr = abs(tp - price) / stop_distance
    now = datetime.now(settings.timezone)
    return TradingViewAlert.model_validate(
        {
            "secret": settings.webhook_secret or "telegram-test",
            "id": f"telegram-test-{int(now.timestamp())}",
            "type": AlertType.EXTENSION,
            "symbol": _settings_symbol(settings),
            "time": now,
            "direction": direction,
            "price": price,
            "ib_high": ib_high,
            "ib_low": ib_low,
            "ib_mid": (ib_high + ib_low) / 2,
            "sl": sl,
            "tp": tp,
            "risk_percent": _settings_risk_percent(settings),
            "rr": rr,
            "source": "telegram",
        }
    )


def _settings_symbol(settings: Settings) -> str:
    if settings.trading_platform.strip().lower() == "bingx":
        return settings.bingx_symbol
    return settings.vanta_symbol


def _settings_risk_percent(settings: Settings) -> float:
    if settings.trading_platform.strip().lower() == "bingx":
        return settings.bingx_risk_percent
    return settings.risk_percent


app = create_app()
