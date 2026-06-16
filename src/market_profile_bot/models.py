from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AlertType(StrEnum):
    IB_READY = "IB_READY"
    RAID = "RAID"
    EXTENSION = "EXTENSION"


class Direction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"


class TradingViewAlert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret: str = Field(min_length=1)
    id: str = Field(min_length=1)
    type: AlertType
    symbol: str = Field(min_length=1)
    time: datetime
    direction: Direction
    price: float
    ib_high: float
    ib_low: float
    ib_mid: float
    sl: float | None = None
    tp: float | None = None
    risk_percent: float = Field(default=1.0, gt=0, le=100)
    rr: float = Field(default=1.0, gt=0)
    source: str = "tradingview"

    @field_validator("ib_mid")
    @classmethod
    def ib_mid_must_be_inside_range(cls, value: float, info):
        high = info.data.get("ib_high")
        low = info.data.get("ib_low")
        if high is not None and low is not None and not low <= value <= high:
            raise ValueError("ib_mid must be between ib_low and ib_high")
        return value

    @field_validator("direction")
    @classmethod
    def direction_must_match_type(cls, value: Direction, info):
        alert_type = info.data.get("type")
        if alert_type == AlertType.IB_READY and value != Direction.NONE:
            raise ValueError("IB_READY alerts must use direction NONE")
        if alert_type in {AlertType.RAID, AlertType.EXTENSION} and value == Direction.NONE:
            raise ValueError("trade alerts must use LONG or SHORT")
        return value

    @field_validator("tp")
    @classmethod
    def risk_levels_must_match_direction(cls, value: float | None, info):
        alert_type = info.data.get("type")
        direction = info.data.get("direction")
        price = info.data.get("price")
        sl = info.data.get("sl")
        if alert_type == AlertType.IB_READY:
            return value
        if price is None or sl is None or value is None:
            raise ValueError("trade alerts must include sl and tp")
        if direction == Direction.LONG and not (sl < price < value):
            raise ValueError("LONG alerts require sl < price < tp")
        if direction == Direction.SHORT and not (value < price < sl):
            raise ValueError("SHORT alerts require tp < price < sl")
        return value
