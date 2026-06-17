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
    ctrader_host_type: str
    ctrader_client_id: str | None
    ctrader_client_secret: str | None
    ctrader_redirect_uri: str | None
    ctrader_access_token: str | None
    ctrader_refresh_token: str | None
    ctrader_account_id: int | None
    ctrader_symbol_id: int | None
    ctrader_symbol_name: str
    ctrader_volume: int
    ctrader_slippage_points: int
    dry_run: bool
    auto_trade: bool
    timezone: ZoneInfo
    entry_cutoff: time
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    telegram_enabled: bool

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        account_id = os.getenv("CTRADER_ACCOUNT_ID")
        symbol_id = os.getenv("CTRADER_SYMBOL_ID")
        return cls(
            webhook_secret=os.getenv("WEBHOOK_SECRET", ""),
            ctrader_host_type=os.getenv("CTRADER_HOST_TYPE", "demo").strip().lower(),
            ctrader_client_id=os.getenv("CTRADER_CLIENT_ID"),
            ctrader_client_secret=os.getenv("CTRADER_CLIENT_SECRET"),
            ctrader_redirect_uri=os.getenv("CTRADER_REDIRECT_URI"),
            ctrader_access_token=os.getenv("CTRADER_ACCESS_TOKEN"),
            ctrader_refresh_token=os.getenv("CTRADER_REFRESH_TOKEN"),
            ctrader_account_id=int(account_id) if account_id else None,
            ctrader_symbol_id=int(symbol_id) if symbol_id else None,
            ctrader_symbol_name=os.getenv("CTRADER_SYMBOL_NAME", "NAS100"),
            ctrader_volume=_int_env("CTRADER_VOLUME", 1000),
            ctrader_slippage_points=_int_env("CTRADER_SLIPPAGE_POINTS", 20),
            dry_run=_bool_env("DRY_RUN", True),
            auto_trade=_bool_env("AUTO_TRADE", False),
            timezone=ZoneInfo(os.getenv("MARKET_TIMEZONE", "America/New_York")),
            entry_cutoff=_time_env("ENTRY_CUTOFF", time(16, 0)),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
            telegram_enabled=_bool_env("TELEGRAM_ENABLED", False),
        )
