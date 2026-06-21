from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException

from .bingx_executor import BingXExecutor
from .config import Settings
from .dedupe import AlertDeduplicator
from .models import AlertType, TradingViewAlert
from .risk import is_entry_allowed
from .telegram import TelegramNotifier
from .trade_limiter import DailyTradeLimiter

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    executor = BingXExecutor(settings)
    dedupe = AlertDeduplicator()
    trade_limiter = DailyTradeLimiter()
    notifier = TelegramNotifier.from_settings(settings)

    app = FastAPI(title="NASDAQ Pre-NYSE IB BingX Bot")

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
        notifier.bot_started(
            backend="bingx",
            dry_run=settings.dry_run,
            auto_trade=settings.auto_trade,
        )

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "backend": "bingx",
            "dry_run": settings.dry_run,
            "auto_trade": settings.auto_trade,
        }

    @app.post("/telegram/webhook")
    def telegram_webhook(update: dict):
        message = update.get("message") or update.get("edited_message") or {}
        chat_id = str(message.get("chat", {}).get("id", ""))
        command = str(message.get("text", "")).strip().split(maxsplit=1)[0].split("@", 1)[0]

        if not notifier.configured or chat_id != str(settings.telegram_chat_id):
            return {"status": "ignored"}
        if command != "/state":
            return {"status": "ignored"}

        try:
            notifier.account_state(executor.current_state(), chat_id=chat_id)
        except RuntimeError as exc:
            logger.exception("Could not retrieve BingX account state")
            notifier.command_error(str(exc), chat_id=chat_id)
        return {"status": "ok"}

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

        result = executor.execute(alert)
        notifier.execution_result(alert, result)
        return {"status": result.status, "detail": result.detail, "order_id": result.order_id}

    return app


app = create_app()
