from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from market_profile_bot.config import Settings
from market_profile_bot.ctrader_executor import CTraderExecutor, ctrader_auth_url
from market_profile_bot.models import TradingViewAlert


def settings(**overrides) -> Settings:
    values = {
        "webhook_secret": "secret",
        "ctrader_host_type": "demo",
        "ctrader_client_id": "client-id",
        "ctrader_client_secret": "client-secret",
        "ctrader_redirect_uri": "http://127.0.0.1:8000/ctrader/callback",
        "ctrader_access_token": None,
        "ctrader_refresh_token": None,
        "ctrader_account_id": None,
        "ctrader_symbol_id": None,
        "ctrader_symbol_name": "NAS100",
        "ctrader_volume": 1000,
        "ctrader_slippage_points": 20,
        "dry_run": True,
        "auto_trade": False,
        "timezone": ZoneInfo("America/New_York"),
        "entry_cutoff": time(16, 0),
        "telegram_bot_token": None,
        "telegram_chat_id": None,
        "telegram_enabled": False,
    }
    values.update(overrides)
    return Settings(**values)


def alert() -> TradingViewAlert:
    return TradingViewAlert.model_validate(
        {
            "secret": "secret",
            "id": "id-1",
            "type": "EXTENSION",
            "symbol": "NAS100",
            "time": datetime.fromisoformat("2026-06-10T10:00:00-04:00"),
            "direction": "LONG",
            "price": 19000.0,
            "ib_high": 18950.0,
            "ib_low": 18850.0,
            "ib_mid": 18900.0,
            "sl": 18850.0,
            "tp": 19150.0,
            "risk_percent": 1.0,
            "rr": 1.0,
            "source": "tradingview",
        }
    )


def test_ctrader_dry_run_does_not_require_live_credentials():
    result = CTraderExecutor(settings()).execute(alert())

    assert result.status == "dry_run"
    assert "NAS100" in result.detail
    assert "volume=1000" in result.detail


def test_ctrader_auth_url_uses_trading_scope():
    url = ctrader_auth_url(settings())

    assert "client_id=client-id" in url
    assert "scope=trading" in url
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A8000%2Fctrader%2Fcallback" in url


def test_ctrader_live_mode_requires_credentials():
    executor = CTraderExecutor(settings(dry_run=False))

    with pytest.raises(RuntimeError, match="CTRADER_ACCESS_TOKEN"):
        executor.execute(alert())


def test_ctrader_accounts_require_access_token():
    executor = CTraderExecutor(settings())

    with pytest.raises(RuntimeError, match="CTRADER_ACCESS_TOKEN"):
        executor.list_accounts()


def test_ctrader_symbols_require_account_id():
    executor = CTraderExecutor(settings(ctrader_access_token="access-token"))

    with pytest.raises(RuntimeError, match="CTRADER_ACCOUNT_ID"):
        executor.list_symbols("NAS")
