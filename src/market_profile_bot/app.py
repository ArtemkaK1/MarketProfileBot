from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException

from .config import Settings
from .dedupe import AlertDeduplicator
from .models import AlertType, TradingViewAlert
from .mt5_executor import MT5Executor
from .risk import is_entry_allowed
from .trade_limiter import DailyTradeLimiter

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    executor = MT5Executor(settings)
    dedupe = AlertDeduplicator()
    trade_limiter = DailyTradeLimiter()

    app = FastAPI(title="NASDAQ Pre-NYSE IB MT5 Bot")

    @app.get("/health")
    def health():
        return {"status": "ok", "dry_run": settings.dry_run, "auto_trade": settings.auto_trade}

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
            return {
                "status": "ib_ready",
                "ib_high": alert.ib_high,
                "ib_low": alert.ib_low,
                "ib_mid": alert.ib_mid,
            }

        if not is_entry_allowed(alert.time, settings.timezone):
            return {"status": "rejected", "reason": "outside_xetra_entry_window"}

        if not settings.auto_trade:
            return {"status": "signal_received", "auto_trade": False, "id": alert.id}

        if not trade_limiter.reserve(alert.time, settings.timezone):
            return {"status": "rejected", "reason": "daily_trade_limit_reached"}

        result = executor.execute(alert)
        return {"status": result.status, "detail": result.detail, "order_id": result.order_id}

    return app


app = create_app()
