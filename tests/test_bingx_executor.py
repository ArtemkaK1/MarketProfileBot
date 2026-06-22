import hashlib
import hmac
from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from market_profile_bot.bingx_executor import (
    BingXExecutor,
    _client_order_id,
    _extract_order_id,
    _query_string,
    adjust_trade_levels,
)
from market_profile_bot.config import Settings
from market_profile_bot.models import TradingViewAlert


def settings(**overrides) -> Settings:
    values = {
        "webhook_secret": "secret",
        "bingx_api_key": None,
        "bingx_secret_key": None,
        "bingx_symbol": "NASDAQ100-USDT",
        "bingx_risk_percent": 5.0,
        "bingx_min_usdt_step": 0.01,
        "bingx_max_notional_usdt": 10000.0,
        "bingx_sl_tp_offset_points": 0.0,
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


def test_bingx_dry_run_uses_live_balance_and_validates_test_order(monkeypatch):
    executor = BingXExecutor(
        settings(bingx_api_key="key", bingx_secret_key="secret")
    )
    monkeypatch.setattr(executor, "_fetch_balance", lambda: Decimal("1100"))
    monkeypatch.setattr(executor, "_resolve_symbol", lambda: "NCSINASDAQ1002USD-USDT")
    monkeypatch.setattr(executor, "_position_side", lambda direction: "LONG")
    requests = []
    monkeypatch.setattr(
        executor,
        "_signed_request",
        lambda method, path, params: requests.append((method, path, params))
        or {"code": 0, "data": {}},
    )

    result = executor.execute(alert())

    assert result.status == "dry_run"
    assert "NASDAQ100-USDT" in result.detail
    assert "quoteOrderQty=5500 USDT" in result.detail
    assert "risk_target=55 USDT" in result.detail
    assert requests[0][1] == "/openApi/swap/v2/trade/order/test"
    assert requests[0][2]["quoteOrderQty"] == "5500"
    assert "quantity" not in requests[0][2]


def test_bingx_live_mode_requires_keys():
    executor = BingXExecutor(settings(dry_run=False))

    with pytest.raises(RuntimeError, match="BINGX_API_KEY"):
        executor.execute(alert())


def test_live_order_runs_preflight_and_safety_checks_before_submission(monkeypatch):
    executor = BingXExecutor(
        settings(
            bingx_api_key="key",
            bingx_secret_key="secret",
            dry_run=False,
        )
    )
    monkeypatch.setattr(executor, "_fetch_balance", lambda: Decimal("100"))
    monkeypatch.setattr(executor, "_resolve_symbol", lambda: "NCSINASDAQ1002USD-USDT")
    monkeypatch.setattr(executor, "_position_side", lambda direction: "LONG")
    safety_checks = []
    monkeypatch.setattr(
        executor,
        "_ensure_no_open_position",
        lambda symbol: safety_checks.append("position"),
    )
    monkeypatch.setattr(
        executor,
        "_ensure_no_strategy_order_today",
        lambda alert, symbol: safety_checks.append("history"),
    )
    requests = []

    def signed_request(method, path, params):
        requests.append((method, path, params))
        if path == "/openApi/swap/v2/trade/order":
            return {"code": 0, "data": {"orderId": "123"}}
        return {"code": 0, "data": {}}

    monkeypatch.setattr(executor, "_signed_request", signed_request)

    result = executor.execute(alert())

    assert result.status == "filled"
    assert result.order_id == 123
    assert safety_checks == ["position", "history"]
    assert [request[1] for request in requests] == [
        "/openApi/swap/v2/trade/order/test",
        "/openApi/swap/v2/trade/order",
    ]
    assert requests[1][2]["quoteOrderQty"] == "500"


def test_bingx_notional_uses_balance_risk_and_rounds_down_to_usdt_step():
    executor = BingXExecutor(settings(bingx_min_usdt_step=0.1))
    sized_alert = alert().model_copy(update={"price": 20000.0, "sl": 19833.0, "tp": 20167.0})

    sizing = executor._calculate_trade_sizing(sized_alert, Decimal("100"))

    assert sizing.balance == Decimal("100")
    assert sizing.risk_amount == Decimal("5")
    assert sizing.quote_order_qty == Decimal("598.8")


def test_bingx_notional_rejects_value_above_hard_limit():
    executor = BingXExecutor(settings(bingx_max_notional_usdt=499.99))

    with pytest.raises(RuntimeError, match="exceeds BINGX_MAX_NOTIONAL_USDT"):
        executor._calculate_trade_sizing(alert(), Decimal("100"))


def test_adjust_trade_levels_moves_long_sl_and_tp_outward():
    adjusted = adjust_trade_levels(alert(), 2.5)

    assert adjusted.sl == 19797.5
    assert adjusted.tp == 20202.5


def test_adjust_trade_levels_moves_short_sl_and_tp_outward():
    short_alert = alert().model_copy(
        update={"direction": "SHORT", "sl": 20200.0, "tp": 19800.0}
    )

    adjusted = adjust_trade_levels(short_alert, 2.5)

    assert adjusted.sl == 20202.5
    assert adjusted.tp == 19797.5


def test_bingx_order_params_map_alert_to_market_order():
    executor = BingXExecutor(settings())

    params = executor._order_params(
        alert(),
        Decimal("500"),
        symbol="NCSINASDAQ1002USD-USDT",
        position_side="LONG",
        client_order_id="mpb-order",
    )

    assert params["symbol"] == "NCSINASDAQ1002USD-USDT"
    assert params["side"] == "BUY"
    assert params["positionSide"] == "LONG"
    assert params["type"] == "MARKET"
    assert params["quoteOrderQty"] == "500"
    assert "quantity" not in params
    assert params["clientOrderId"] == "mpb-order"
    assert "STOP_MARKET" in params["stopLoss"]
    assert "TAKE_PROFIT_MARKET" in params["takeProfit"]


def test_query_string_sorts_params_for_signature():
    assert _query_string({"b": 2, "a": 1}) == "a=1&b=2"


def test_signed_post_uses_raw_canonical_body_for_attached_sl_tp(monkeypatch):
    executor = BingXExecutor(
        settings(bingx_api_key="key", bingx_secret_key="secret")
    )
    params = {
        "symbol": "BTC-USDT",
        "stopLoss": '{"type":"STOP_MARKET","stopPrice":100}',
        "timestamp": 123,
    }
    captured = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'{"code":0,"data":{}}'

    def fake_urlopen(req, timeout):
        captured.append(req)
        return Response()

    monkeypatch.setattr("market_profile_bot.bingx_executor.request.urlopen", fake_urlopen)

    executor._signed_request("POST", "/order/test", params)

    canonical = (
        'stopLoss={"type":"STOP_MARKET","stopPrice":100}'
        "&symbol=BTC-USDT&timestamp=123"
    )
    signature = hmac.new(b"secret", canonical.encode(), hashlib.sha256).hexdigest()
    assert captured[0].full_url == "https://open-api.bingx.com/order/test"
    assert captured[0].data.decode() == f"{canonical}&signature={signature}"
    assert captured[0].headers["Content-type"] == "application/x-www-form-urlencoded"
    assert captured[0].headers["X-source-key"] == "BX-AI-SKILL"


def test_extract_order_id_accepts_common_bingx_response_shape():
    assert _extract_order_id({"data": {"orderId": "123"}}) == 123
    assert _extract_order_id({"orderId": 456}) == 456
    assert _extract_order_id({"data": {"orderId": "not-numeric"}}) is None


@pytest.mark.parametrize(
    ("dual_side_value", "direction", "expected"),
    [(True, "LONG", "LONG"), (True, "SHORT", "SHORT"), (False, "LONG", "BOTH")],
)
def test_position_side_matches_bingx_account_mode(
    monkeypatch, dual_side_value, direction, expected
):
    executor = BingXExecutor(settings(bingx_api_key="key", bingx_secret_key="secret"))
    monkeypatch.setattr(
        executor,
        "_signed_request",
        lambda method, path, params: {
            "code": 0,
            "data": {"dualSidePosition": dual_side_value},
        },
    )

    assert executor._position_side(direction) == expected


def test_client_order_id_is_stable_and_within_bingx_limit():
    first = _client_order_id("a-very-long-tradingview-alert-id" * 3)

    assert first == _client_order_id("a-very-long-tradingview-alert-id" * 3)
    assert first != _client_order_id("different-alert-id")
    assert len(first) <= 40


def test_open_position_blocks_live_order(monkeypatch):
    executor = BingXExecutor(settings(bingx_api_key="key", bingx_secret_key="secret"))
    monkeypatch.setattr(
        executor,
        "_signed_request",
        lambda method, path, params: {
            "code": 0,
            "data": [{"positionAmt": "0.25"}],
        },
    )

    with pytest.raises(RuntimeError, match="open BingX position already exists"):
        executor._ensure_no_open_position("NCSINASDAQ1002USD-USDT")


def test_strategy_order_history_survives_process_restart(monkeypatch):
    executor = BingXExecutor(settings(bingx_api_key="key", bingx_secret_key="secret"))
    monkeypatch.setattr(
        executor,
        "_signed_request",
        lambda method, path, params: {
            "code": 0,
            "data": {"orders": [{"clientOrderId": "mpb-existing"}]},
        },
    )

    with pytest.raises(RuntimeError, match="already been placed"):
        executor._ensure_no_strategy_order_today(
            alert(), "NCSINASDAQ1002USD-USDT"
        )


def test_current_state_combines_balance_margin_and_leverage(monkeypatch):
    executor = BingXExecutor(settings(bingx_api_key="key", bingx_secret_key="secret"))
    monkeypatch.setattr(executor, "_resolve_symbol", lambda: "NCSINASDAQ1002USD-USDT")
    responses = {
        "/openApi/swap/v2/user/balance": {
            "code": 0,
            "data": {"balance": {"balance": "123.45", "availableMargin": "98.76"}},
        },
        "/openApi/swap/v2/trade/marginType": {
            "code": 0,
            "data": {"marginType": "CROSSED"},
        },
        "/openApi/swap/v2/trade/leverage": {
            "code": 0,
            "data": {"longLeverage": 10, "shortLeverage": 5},
        },
    }
    monkeypatch.setattr(
        executor,
        "_signed_request",
        lambda method, path, params: responses[path],
    )

    state = executor.current_state()

    assert state.symbol == "NASDAQ100-USDT"
    assert state.balance == Decimal("123.45")
    assert state.available_margin == Decimal("98.76")
    assert state.margin_type == "CROSSED"
    assert state.long_leverage == Decimal("10")
    assert state.short_leverage == Decimal("5")


def test_resolve_symbol_maps_usdt_display_alias_and_caches_result(monkeypatch):
    executor = BingXExecutor(settings(bingx_symbol="NASDAQ100"))
    calls = []
    monkeypatch.setattr(
        executor,
        "_public_request",
        lambda path: calls.append(path)
        or {
            "code": 0,
            "data": [
                {
                    "symbol": "NCSINASDAQ1002USD-USDT",
                    "displayName": "NASDAQ100-USDT",
                    "currency": "USDT",
                }
            ],
        },
    )

    assert executor._resolve_symbol() == "NCSINASDAQ1002USD-USDT"
    assert executor._resolve_symbol() == "NCSINASDAQ1002USD-USDT"
    assert calls == ["/openApi/swap/v2/quote/contracts"]


def test_resolve_symbol_rejects_unknown_contract(monkeypatch):
    executor = BingXExecutor(settings(bingx_symbol="UNKNOWN-USDT"))
    monkeypatch.setattr(
        executor,
        "_public_request",
        lambda path: {"code": 0, "data": []},
    )

    with pytest.raises(RuntimeError, match="UNKNOWN-USDT.*not found"):
        executor._resolve_symbol()


def test_current_state_requires_api_keys():
    with pytest.raises(RuntimeError, match="BINGX_API_KEY"):
        BingXExecutor(settings()).current_state()
