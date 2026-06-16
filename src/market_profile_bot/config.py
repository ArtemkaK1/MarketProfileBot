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
    mt5_login: int | None
    mt5_password: str | None
    mt5_server: str | None
    mt5_symbol: str
    mt5_volume: float
    mt5_deviation: int
    mt5_magic: int
    mt5_sl_points: float | None
    mt5_tp_points: float | None
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
        login = os.getenv("MT5_LOGIN")
        return cls(
            webhook_secret=os.getenv("WEBHOOK_SECRET", ""),
            mt5_login=int(login) if login else None,
            mt5_password=os.getenv("MT5_PASSWORD"),
            mt5_server=os.getenv("MT5_SERVER"),
            mt5_symbol=os.getenv("MT5_SYMBOL", "NAS100"),
            mt5_volume=float(os.getenv("MT5_VOLUME", "0.10")),
            mt5_deviation=_int_env("MT5_DEVIATION", 20),
            mt5_magic=_int_env("MT5_MAGIC", 404011),
            mt5_sl_points=_float_env("MT5_SL_POINTS"),
            mt5_tp_points=_float_env("MT5_TP_POINTS"),
            dry_run=_bool_env("DRY_RUN", True),
            auto_trade=_bool_env("AUTO_TRADE", False),
            timezone=ZoneInfo(os.getenv("MARKET_TIMEZONE", "America/New_York")),
            entry_cutoff=_time_env("ENTRY_CUTOFF", time(16, 0)),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
            telegram_enabled=_bool_env("TELEGRAM_ENABLED", False),
        )
