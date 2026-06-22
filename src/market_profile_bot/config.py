from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BINGX_BASE_URL = "https://open-api.bingx.com"
BINGX_SIZE_FIELD = "quoteOrderQty"
BINGX_ORDER_ENDPOINT = "/openApi/swap/v2/trade/order"
BINGX_TEST_ORDER_ENDPOINT = "/openApi/swap/v2/trade/order/test"
BINGX_BALANCE_ENDPOINT = "/openApi/swap/v2/user/balance"
BINGX_MARGIN_TYPE_ENDPOINT = "/openApi/swap/v2/trade/marginType"
BINGX_LEVERAGE_ENDPOINT = "/openApi/swap/v2/trade/leverage"
BINGX_CONTRACTS_ENDPOINT = "/openApi/swap/v2/quote/contracts"
BINGX_POSITION_MODE_ENDPOINT = "/openApi/swap/v1/positionSide/dual"
BINGX_POSITIONS_ENDPOINT = "/openApi/swap/v2/user/positions"
BINGX_FULL_ORDER_ENDPOINT = "/openApi/swap/v1/trade/fullOrder"
BINGX_RECV_WINDOW = 5000
BINGX_ENABLE_SL_TP = True


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
