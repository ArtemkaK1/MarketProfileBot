import base64
import hashlib
import hmac
import json
from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from market_profile_bot.config import Settings
from market_profile_bot.models import TradingViewAlert
from market_profile_bot.platforms.vanta_trading.executor import (
    VANTA_ORDERS_ENDPOINT,
    VantaTradingExecutor,
    _extract_order_id,
)
from market_profile_bot.trading import AccountState


def settings(**overrides) -> Settings:
    values = {
        "webhook_secret": "secret",
        "trading_platform": "vanta_trading",
        "vanta_key_id": "key",
        "vanta_secret": "secret",
        "vanta_account_id": "bba0bc1c-7cb1-494c-b32b-fa64277e1cfb",
        "vanta_base_url": "https://app.vantatrading.io",
        "vanta_symbol": "XYZ100/USDC",
        "vanta_account_balance": 5000.0,
        "vanta_leverage": 1.5,
        "risk_percent": 1.0,
        "min_quote_step": 0.01,
        "max_notional_usdc": None,
        "sl_tp_offset_points": 0.0,
        "bingx_api_key": None,
        "bingx_secret_key": None,
        "bingx_symbol": "NASDAQ100-USDT",
        "bingx_risk_percent": 5.0,
        "bingx_min_usdt_step": 0.01,
        "bingx_max_notional_usdt": 1000.0,
        "bingx_sl_tp_offset_points": 2.5,
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
            "risk_percent": 1.0,
            "rr": 1.0,
            "source": "tradingview",
        }
    )


def test_vanta_dry_run_uses_account_balance_and_prepares_order(monkeypatch):
    executor = VantaTradingExecutor(settings())
    monkeypatch.setattr(
        executor,
        "current_state",
        lambda: AccountState(
            platform="VantaTrading",
            symbol="XYZ100/USDC",
            balance=Decimal("5000"),
            buying_power=Decimal("7500"),
            available_margin=Decimal("7500"),
            leverage=Decimal("1.5"),
            currency="USDC",
        ),
    )

    result = executor.execute(alert())

    assert result.status == "dry_run"
    assert "XYZ100/USDC" in result.detail
    assert "risk_target=50 USDC" in result.detail
    assert "value=5000 USDC" in result.detail


def test_vanta_live_order_checks_position_then_posts_order(monkeypatch):
    executor = VantaTradingExecutor(settings(dry_run=False))
    monkeypatch.setattr(
        executor,
        "current_state",
        lambda: AccountState(
            platform="VantaTrading",
            symbol="XYZ100/USDC",
            balance=Decimal("1000"),
            buying_power=Decimal("10000"),
            available_margin=Decimal("10000"),
            leverage=Decimal("10"),
            currency="USDC",
        ),
    )
    safety_checks = []
    monkeypatch.setattr(
        executor, "_ensure_no_open_position", lambda: safety_checks.append("position")
    )
    requests = []

    def signed_request(method, path, body=None):
        requests.append((method, path, body))
        if path == VANTA_ORDERS_ENDPOINT:
            return {"id": "123"}
        return {}

    monkeypatch.setattr(executor, "_signed_request", signed_request)

    result = executor.execute(alert())

    assert result.status == "filled"
    assert result.order_id == 123
    assert safety_checks == ["position"]
    assert requests == [
        (
            "POST",
            "/api/v1/trading/orders",
            {
                "accountId": "bba0bc1c-7cb1-494c-b32b-fa64277e1cfb",
                "trade": {
                    "execution_type": "MARKET",
                    "trade_pair": "XYZ100/USDC",
                    "order_type": "LONG",
                    "value": 1000.0,
                },
            },
        )
    ]


def test_vanta_live_order_caps_value_to_buying_power(monkeypatch):
    executor = VantaTradingExecutor(settings(dry_run=False))
    monkeypatch.setattr(
        executor,
        "current_state",
        lambda: AccountState(
            platform="VantaTrading",
            symbol="XYZ100/USDC",
            balance=Decimal("5000"),
            buying_power=Decimal("7500"),
            available_margin=Decimal("7500"),
            leverage=Decimal("1.5"),
            currency="USDC",
        ),
    )
    monkeypatch.setattr(executor, "_ensure_no_open_position", lambda: None)
    requests = []

    def signed_request(method, path, body=None):
        requests.append((method, path, body))
        return {"id": "123"}

    monkeypatch.setattr(executor, "_signed_request", signed_request)

    result = executor.execute(alert().model_copy(update={"sl": 19900.0}))

    assert result.status == "filled"
    assert requests[0][2]["trade"]["value"] == 7500.0


def test_current_state_uses_api_values_and_falls_back_to_config_leverage(monkeypatch):
    executor = VantaTradingExecutor(settings())
    monkeypatch.setattr(
        executor,
        "_signed_request",
        lambda method, path, body=None: {"balance": "5000"},
    )

    state = executor.current_state()

    assert state.balance == Decimal("5000")
    assert state.buying_power == Decimal("7500.0")
    assert state.available_margin == Decimal("7500.0")
    assert state.leverage == Decimal("1.5")


def test_current_state_parses_formatted_vanta_decimal_values(monkeypatch):
    executor = VantaTradingExecutor(settings())
    monkeypatch.setattr(
        executor,
        "_signed_request",
        lambda method, path, body=None: {
            "data": {
                "account": {
                    "balance": "5,000 USDC",
                    "leverage": "1:1.5",
                    "buyingPower": "7,500.00 USDC",
                    "availableMargin": {"value": "7,250 USDC"},
                }
            }
        },
    )

    state = executor.current_state()

    assert state.balance == Decimal("5000")
    assert state.leverage == Decimal("1.5")
    assert state.buying_power == Decimal("7500.00")
    assert state.available_margin == Decimal("7250")


def test_current_state_falls_back_when_leverage_field_is_not_numeric(monkeypatch):
    executor = VantaTradingExecutor(settings(vanta_leverage=1.5))
    monkeypatch.setattr(
        executor,
        "_signed_request",
        lambda method, path, body=None: {
            "balance": "5000",
            "leverage": "prop default",
        },
    )

    state = executor.current_state()

    assert state.leverage == Decimal("1.5")
    assert state.buying_power == Decimal("7500.0")


def test_current_state_handles_vanta_display_leverage_response(monkeypatch):
    executor = VantaTradingExecutor(settings(vanta_leverage=1.5))
    monkeypatch.setattr(
        executor,
        "_signed_request",
        lambda method, path, body=None: {
            "balanceChange": 0,
            "balanceChangePercent": 0,
            "capitalUsed": 0,
            "currentBalance": 5000,
            "currentEquity": 5000,
            "isPassed": False,
            "leverage": "Current - 0.0000x / Max - 10x",
            "openPnL": 0,
            "openPnLPercent": 0,
            "openPositions": 0,
            "portfolioBalance": 30000,
            "portfolioBalanceBreakdown": {
                "currentBalance": 5000,
                "marginLeverage": 2,
                "sumPositionValue": 0,
            },
            "portfolioBalanceChangePercent": 200,
            "totalPnL": 0,
            "totalPnLPercent": 0,
            "totalRealizedPnl": 0,
        },
    )

    state = executor.current_state()

    assert state.balance == Decimal("5000")
    assert state.leverage == Decimal("1.5")
    assert state.buying_power == Decimal("7500.0")


def test_signed_request_uses_vanta_canonical_signature(monkeypatch):
    executor = VantaTradingExecutor(settings())
    captured = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'{"id":123}'

    def fake_urlopen(req, timeout):
        captured.append(req)
        return Response()

    monkeypatch.setattr("market_profile_bot.platforms.vanta_trading.executor.time.time", lambda: 1)
    monkeypatch.setattr(
        "market_profile_bot.platforms.vanta_trading.executor.secrets.token_hex",
        lambda length: "abc123",
    )
    monkeypatch.setattr(
        "market_profile_bot.platforms.vanta_trading.executor.request.urlopen",
        fake_urlopen,
    )

    body = {"accountId": "account", "trade": {"value": 1000}}
    executor._signed_request("POST", VANTA_ORDERS_ENDPOINT, body)

    body_bytes = json.dumps(body, separators=(",", ":")).encode("utf-8")
    body_hash = hashlib.sha256(body_bytes).hexdigest()
    canonical = f"v1\nPOST\n{VANTA_ORDERS_ENDPOINT}\n1000\nabc123\n{body_hash}"
    signature = base64.b64encode(
        hmac.new(b"secret", canonical.encode("utf-8"), hashlib.sha256).digest()
    ).decode("ascii")
    req = captured[0]
    assert req.full_url == "https://app.vantatrading.io/api/v1/trading/orders"
    assert req.data == body_bytes
    assert req.headers["X-vanta-key-id"] == "key"
    assert req.headers["X-vanta-timestamp"] == "1000"
    assert req.headers["X-vanta-nonce"] == "abc123"
    assert req.headers["X-vanta-signature"] == f"v1={signature}"


def test_extract_order_id_accepts_common_vanta_response_shape():
    assert _extract_order_id({"data": {"order_id": "123"}}) == 123
    assert _extract_order_id({"id": 456}) == 456
    assert _extract_order_id({"data": {"id": "not-numeric"}}) is None


def test_current_state_requires_api_keys():
    with pytest.raises(RuntimeError, match="VANTA_KEY_ID"):
        VantaTradingExecutor(settings(vanta_key_id=None)).current_state()
