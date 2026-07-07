from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float | None = None) -> float | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return float(value)


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def _time_env(name: str, default: time) -> time:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    hour, minute = value.split(":", maxsplit=1)
    return time(int(hour), int(minute))


@dataclass(frozen=True)
class Settings:
    webhook_secret: str
    trading_platform: str
    vanta_key_id: str | None
    vanta_secret: str | None
    vanta_account_id: str
    vanta_base_url: str
    vanta_symbol: str
    vanta_account_balance: float
    vanta_leverage: float
    risk_percent: float
    min_quote_step: float
    max_notional_usdc: float | None
    sl_tp_offset_points: float
    bingx_api_key: str | None
    bingx_secret_key: str | None
    bingx_symbol: str
    bingx_risk_percent: float
    bingx_min_usdt_step: float
    bingx_max_notional_usdt: float
    bingx_sl_tp_offset_points: float
    dry_run: bool
    auto_trade: bool
    timezone: ZoneInfo
    entry_cutoff: time
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    telegram_enabled: bool

    @property
    def telegram_webhook_url(self) -> str | None:
        explicit_url = os.getenv("TELEGRAM_WEBHOOK_URL", "").strip()
        if explicit_url:
            explicit_url = explicit_url.rstrip("/")
            if explicit_url.endswith("/telegram/webhook"):
                return explicit_url
            return explicit_url + "/telegram/webhook"
        railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
        if railway_domain:
            return f"https://{railway_domain}/telegram/webhook"
        return None

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            webhook_secret=os.getenv("WEBHOOK_SECRET", ""),
            trading_platform=os.getenv("TRADING_PLATFORM", "vanta_trading"),
            vanta_key_id=os.getenv("VANTA_KEY_ID"),
            vanta_secret=os.getenv("VANTA_SECRET"),
            vanta_account_id=os.getenv(
                "VANTA_ACCOUNT_ID", "bba0bc1c-7cb1-494c-b32b-fa64277e1cfb"
            ),
            vanta_base_url=os.getenv("VANTA_BASE_URL", "https://app.vantatrading.io"),
            vanta_symbol=os.getenv("VANTA_SYMBOL", "XYZ100/USDC"),
            vanta_account_balance=float(os.getenv("VANTA_ACCOUNT_BALANCE", "5000")),
            vanta_leverage=float(os.getenv("VANTA_LEVERAGE", "1.5")),
            risk_percent=float(os.getenv("RISK_PERCENT", "1.0")),
            min_quote_step=float(os.getenv("MIN_QUOTE_STEP", "0.01")),
            max_notional_usdc=_float_env("MAX_NOTIONAL_USDC"),
            sl_tp_offset_points=float(os.getenv("SL_TP_OFFSET_POINTS", "0")),
            bingx_api_key=os.getenv("BINGX_API_KEY"),
            bingx_secret_key=os.getenv("BINGX_SECRET_KEY"),
            bingx_symbol=os.getenv("BINGX_SYMBOL", "NASDAQ100-USDT"),
            bingx_risk_percent=float(os.getenv("BINGX_RISK_PERCENT", "5.0")),
            bingx_min_usdt_step=float(os.getenv("BINGX_MIN_USDT_STEP", "0.01")),
            bingx_max_notional_usdt=float(
                os.getenv("BINGX_MAX_NOTIONAL_USDT", "1000")
            ),
            bingx_sl_tp_offset_points=float(
                os.getenv("BINGX_SL_TP_OFFSET_POINTS", "2.5")
            ),
            dry_run=_bool_env("DRY_RUN", True),
            auto_trade=_bool_env("AUTO_TRADE", False),
            timezone=ZoneInfo(os.getenv("MARKET_TIMEZONE", "America/New_York")),
            entry_cutoff=_time_env("ENTRY_CUTOFF", time(16, 0)),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
            telegram_enabled=_bool_env("TELEGRAM_ENABLED", False),
        )
