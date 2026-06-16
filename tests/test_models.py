from datetime import datetime

import pytest
from pydantic import ValidationError

from market_profile_bot.models import TradingViewAlert


def valid_payload(**overrides):
    payload = {
        "secret": "secret",
        "id": "id-1",
        "type": "RAID",
        "symbol": "NAS100",
        "time": datetime.fromisoformat("2026-06-10T12:00:00+02:00"),
        "direction": "SHORT",
        "price": 18425.5,
        "ib_high": 18510.0,
        "ib_low": 18390.0,
        "ib_mid": 18450.0,
        "sl": 18510.0,
        "tp": 18341.0,
        "risk_percent": 1.0,
        "rr": 1.0,
        "source": "tradingview",
    }
    payload.update(overrides)
    return payload


def test_trade_alert_requires_direction():
    with pytest.raises(ValidationError):
        TradingViewAlert.model_validate(valid_payload(direction="NONE"))


def test_ib_ready_requires_none_direction():
    alert = TradingViewAlert.model_validate(valid_payload(type="IB_READY", direction="NONE", sl=None, tp=None))
    assert alert.type == "IB_READY"


def test_ib_mid_must_be_inside_range():
    with pytest.raises(ValidationError):
        TradingViewAlert.model_validate(valid_payload(ib_mid=19000))


def test_trade_alert_requires_sl_and_tp():
    with pytest.raises(ValidationError):
        TradingViewAlert.model_validate(valid_payload(sl=None, tp=None))


def test_trade_alert_requires_risk_levels_on_correct_side():
    with pytest.raises(ValidationError):
        TradingViewAlert.model_validate(valid_payload(direction="SHORT", sl=18300.0, tp=18500.0))
