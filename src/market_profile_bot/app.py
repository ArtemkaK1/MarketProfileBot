from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException

from .config import Settings
from .ctrader_executor import (
    CTraderExecutor,
    ctrader_auth_url,
    exchange_authorization_code,
    refresh_access_token,
)
from .dedupe import AlertDeduplicator
from .models import AlertType, TradingViewAlert
from .risk import is_entry_allowed
from .telegram import TelegramNotifier
from .trade_limiter import DailyTradeLimiter

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    executor = CTraderExecutor(settings)
    dedupe = AlertDeduplicator()
    trade_limiter = DailyTradeLimiter()
    notifier = TelegramNotifier.from_settings(settings)

    app = FastAPI(title="NASDAQ Pre-NYSE IB cTrader Bot")

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "backend": "ctrader",
            "dry_run": settings.dry_run,
            "auto_trade": settings.auto_trade,
        }

    @app.get("/ctrader/auth-url")
    def get_ctrader_auth_url():
        try:
            return {"auth_url": ctrader_auth_url(settings)}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/ctrader/callback")
    def ctrader_callback(code: str):
        try:
            token = exchange_authorization_code(settings, code)
            return {
                "status": "ok",
                "save_to_env": {
                    "CTRADER_ACCESS_TOKEN": token.get("accessToken"),
                    "CTRADER_REFRESH_TOKEN": token.get("refreshToken"),
                },
                "raw": token,
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/ctrader/refresh-token")
    def refresh_ctrader_token():
        try:
            token = refresh_access_token(settings)
            return {
                "status": "ok",
                "save_to_env": {
                    "CTRADER_ACCESS_TOKEN": token.get("accessToken"),
                    "CTRADER_REFRESH_TOKEN": token.get("refreshToken"),
                },
                "raw": token,
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/ctrader/accounts")
    def get_ctrader_accounts():
        try:
            return {"accounts": executor.list_accounts()}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/ctrader/symbols")
    def get_ctrader_symbols(q: str | None = None):
        try:
            return {"symbols": executor.list_symbols(q)}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

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
