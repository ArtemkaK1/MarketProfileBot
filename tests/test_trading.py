from datetime import datetime
from decimal import Decimal

from market_profile_bot.models import TradingViewAlert
from market_profile_bot.trading import adjust_trade_levels, calculate_quote_order_qty


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


def test_quote_size_uses_balance_risk_and_rounds_down_to_step():
    sizing = calculate_quote_order_qty(
        alert().model_copy(update={"price": 20000.0, "sl": 19833.0}),
        balance=Decimal("5000"),
        risk_percent=1,
        min_quote_step=0.1,
        buying_power=Decimal("7500"),
        platform_name="VantaTrading",
    )

    assert sizing.balance == Decimal("5000")
    assert sizing.target_risk_amount == Decimal("50")
    assert sizing.risk_amount == Decimal("49.9998")
    assert sizing.quote_order_qty == Decimal("5988.0")
    assert sizing.buying_power == Decimal("7500")
    assert not sizing.capped_by_buying_power


def test_quote_size_caps_to_buying_power_and_reduces_actual_risk():
    sizing = calculate_quote_order_qty(
        alert().model_copy(update={"sl": 19900.0}),
        balance=Decimal("5000"),
        risk_percent=1,
        min_quote_step=0.01,
        buying_power=Decimal("7500"),
        platform_name="VantaTrading",
    )

    assert sizing.target_risk_amount == Decimal("50")
    assert sizing.quote_order_qty == Decimal("7500")
    assert sizing.risk_amount == Decimal("37.5")
    assert sizing.capped_by_buying_power


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
