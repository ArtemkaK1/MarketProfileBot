from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from market_profile_bot.bingx_executor import BingXExecutor, _extract_order_id, _query_string
from market_profile_bot.config import Settings
from market_profile_bot.models import TradingViewAlert


def settings(**overrides) -> Settings:
    values = {
        "webhook_secret": "secret",
        "bingx_api_key": None,
        "bingx_secret_key": None,
        "bingx_symbol": "NASDAQ100-USDT",
        "bingx_initial_capital": 100.0,
        "bingx_risk_percent": 5.0,
        "bingx_min_usdt_step": 0.01,
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
            "price": 20000.0,
            "ib_high": 19950.0,
            "ib_low": 19850.0,
            "ib_mid": 19900.0,
            "sl": 19800.0,
            "tp": 20200.0,
            "risk_percent": 5.0,
            "rr": 1.0,
            "source": "tradingview",
        }
    )


def test_bingx_dry_run_calculates_usdt_size():
    result = BingXExecutor(settings()).execute(alert())

    assert result.status == "dry_run"
    assert "NASDAQ100-USDT" in result.detail
    assert "quantity=500.0" in result.detail
    assert "risk_target=5.0" in result.detail


def test_bingx_live_mode_requires_keys():
    executor = BingXExecutor(settings(dry_run=False))

    with pytest.raises(RuntimeError, match="BINGX_API_KEY"):
        executor.execute(alert())


def test_bingx_size_rounds_up_to_min_usdt_step():
    executor = BingXExecutor(settings(bingx_min_usdt_step=0.1))
    sized_alert = alert().model_copy(update={"price": 20000.0, "sl": 19833.0, "tp": 20167.0})

    assert executor._calculate_usdt_size(sized_alert) == 598.9


def test_bingx_order_params_map_alert_to_market_order():
    executor = BingXExecutor(settings())

    params = executor._order_params(alert(), 500.0)

    assert params["symbol"] == "NASDAQ100-USDT"
    assert params["side"] == "BUY"
    assert params["positionSide"] == "LONG"
    assert params["type"] == "MARKET"
    assert params["quantity"] == "500"
    assert "STOP_MARKET" in params["stopLoss"]
    assert "TAKE_PROFIT_MARKET" in params["takeProfit"]


def test_query_string_sorts_params_for_signature():
    assert _query_string({"b": 2, "a": 1}) == "a=1&b=2"


def test_extract_order_id_accepts_common_bingx_response_shape():
    assert _extract_order_id({"data": {"orderId": "123"}}) == 123
    assert _extract_order_id({"orderId": 456}) == 456
    assert _extract_order_id({"data": {"orderId": "not-numeric"}}) is None
