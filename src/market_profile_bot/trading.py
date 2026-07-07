from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from typing import Protocol

from .execution import ExecutionResult
from .models import Direction, TradingViewAlert


@dataclass(frozen=True)
class AccountState:
    platform: str
    symbol: str
    balance: Decimal
    buying_power: Decimal | None = None
    available_margin: Decimal | None = None
    leverage: Decimal | None = None
    margin_type: str | None = None
    long_leverage: Decimal | None = None
    short_leverage: Decimal | None = None
    currency: str = "USDC"


@dataclass(frozen=True)
class TradeSizing:
    balance: Decimal
    risk_amount: Decimal
    quote_order_qty: Decimal
    buying_power: Decimal | None = None
    target_risk_amount: Decimal | None = None
    capped_by_buying_power: bool = False


class TradingExecutor(Protocol):
    platform_name: str

    def execute(self, alert: TradingViewAlert) -> ExecutionResult:
        ...

    def current_state(self) -> AccountState:
        ...


def calculate_quote_order_qty(
    alert: TradingViewAlert,
    *,
    balance: Decimal,
    risk_percent: float,
    min_quote_step: float,
    max_notional: Decimal | None = None,
    buying_power: Decimal | None = None,
    platform_name: str = "platform",
) -> TradeSizing:
    if alert.sl is None:
        raise RuntimeError(f"Cannot calculate {platform_name} size: alert sl is missing")
    entry = Decimal(str(alert.price))
    stop_distance = abs(entry - Decimal(str(alert.sl)))
    if entry <= 0:
        raise RuntimeError(f"Cannot calculate {platform_name} size: entry price must be > 0")
    if stop_distance <= 0:
        raise RuntimeError(f"Cannot calculate {platform_name} size: stop distance must be > 0")
    if balance <= 0:
        raise RuntimeError(f"Cannot calculate {platform_name} size: balance must be > 0")
    if not 0 < risk_percent <= 100:
        raise RuntimeError(f"{platform_name} risk percent must be > 0 and <= 100")
    if min_quote_step <= 0:
        raise RuntimeError(f"{platform_name} quote step must be > 0")

    target_risk_amount = balance * Decimal(str(risk_percent)) / Decimal("100")
    step = Decimal(str(min_quote_step))
    raw_notional = target_risk_amount * entry / stop_distance
    quote_order_qty = (
        raw_notional / step
    ).to_integral_value(rounding=ROUND_FLOOR) * step
    if quote_order_qty <= 0:
        raise RuntimeError(f"Calculated {platform_name} notional is below the quote step")

    effective_limit = buying_power if max_notional is None else max_notional
    if buying_power is not None and effective_limit is not None:
        effective_limit = min(effective_limit, buying_power)
    capped_by_buying_power = False
    if effective_limit is not None and quote_order_qty > effective_limit:
        quote_order_qty = (
            effective_limit / step
        ).to_integral_value(rounding=ROUND_FLOOR) * step
        capped_by_buying_power = True
        if quote_order_qty <= 0:
            raise RuntimeError(f"Available {platform_name} limit is below the quote step")

    risk_amount = quote_order_qty * stop_distance / entry

    return TradeSizing(
        balance=balance,
        risk_amount=risk_amount,
        quote_order_qty=quote_order_qty,
        buying_power=buying_power,
        target_risk_amount=target_risk_amount,
        capped_by_buying_power=capped_by_buying_power,
    )


def adjust_trade_levels(
    alert: TradingViewAlert, offset_points: float
) -> TradingViewAlert:
    if alert.direction == Direction.NONE or offset_points == 0:
        return alert
    if alert.sl is None or alert.tp is None:
        raise RuntimeError("Cannot adjust trade levels: alert sl or tp is missing")
    offset = float(offset_points)
    if alert.direction == Direction.LONG:
        sl = alert.sl - offset
        tp = alert.tp + offset
    else:
        sl = alert.sl + offset
        tp = alert.tp - offset
    return alert.model_copy(update={"sl": sl, "tp": tp})


def client_order_id(alert_id: str, *, prefix: str = "mpb", max_length: int = 40) -> str:
    import hashlib

    digest = hashlib.sha256(alert_id.encode("utf-8")).hexdigest()
    return f"{prefix}-{digest[: max_length - len(prefix) - 1]}"


def number_text(value: float | Decimal) -> str:
    return _number_text(value)


def _number_text(value: float | Decimal) -> str:
    return format(Decimal(str(value)).normalize(), "f")
