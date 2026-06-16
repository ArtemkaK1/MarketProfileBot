from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from .config import Settings
from .models import Direction, TradingViewAlert

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    detail: str
    order_id: int | None = None


class MT5Executor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._mt5 = None

    def _load_mt5(self):
        if self._mt5 is None:
            import MetaTrader5 as mt5

            self._mt5 = mt5
        return self._mt5

    def connect(self) -> None:
        if self.settings.dry_run:
            return

        mt5 = self._load_mt5()
        if not mt5.initialize():
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")

        if self.settings.mt5_login and self.settings.mt5_password and self.settings.mt5_server:
            ok = mt5.login(
                self.settings.mt5_login,
                password=self.settings.mt5_password,
                server=self.settings.mt5_server,
            )
            if not ok:
                raise RuntimeError(f"MT5 login failed: {mt5.last_error()}")

    def execute(self, alert: TradingViewAlert) -> ExecutionResult:
        if alert.direction == Direction.NONE:
            return ExecutionResult("ignored", "IB_READY does not open a position")

        if self.settings.dry_run:
            logger.info("DRY_RUN trade alert: %s", alert.model_dump())
            return ExecutionResult(
                "dry_run",
                f"{alert.direction} {self.settings.mt5_symbol} risk={alert.risk_percent}% sl={alert.sl} tp={alert.tp}",
            )

        self.connect()
        mt5 = self._load_mt5()

        symbol = self.settings.mt5_symbol or alert.symbol
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"No MT5 tick data for symbol {symbol}")
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            raise RuntimeError(f"No MT5 symbol info for {symbol}")
        account_info = mt5.account_info()
        if account_info is None:
            raise RuntimeError(f"No MT5 account info: {mt5.last_error()}")

        order_type = mt5.ORDER_TYPE_BUY if alert.direction == Direction.LONG else mt5.ORDER_TYPE_SELL
        price = tick.ask if alert.direction == Direction.LONG else tick.bid
        sl = alert.sl if alert.sl is not None else self._stop_loss(price, alert.direction)
        if sl is None:
            raise RuntimeError("Trade alert must include sl and tp for 1% risk and 1:1 RR execution")
        tp = self._take_profit_for_rr(price, sl, alert.direction, alert.rr)
        volume = self._risk_volume(
            price=price,
            sl=sl,
            risk_percent=alert.risk_percent,
            account_info=account_info,
            symbol_info=symbol_info,
        )

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "deviation": self.settings.mt5_deviation,
            "magic": self.settings.mt5_magic,
            "comment": f"{alert.type} {alert.id}"[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        if sl is not None:
            request["sl"] = sl
        if tp is not None:
            request["tp"] = tp

        result = mt5.order_send(request)
        if result is None:
            raise RuntimeError(f"MT5 order_send returned None: {mt5.last_error()}")
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"MT5 order failed retcode={result.retcode}: {result}")

        return ExecutionResult("filled", "MT5 order opened", order_id=result.order)

    def _stop_loss(self, price: float, direction: Direction) -> float | None:
        points = self.settings.mt5_sl_points
        if points is None:
            return None
        return price - points if direction == Direction.LONG else price + points

    def _take_profit(self, price: float, direction: Direction) -> float | None:
        points = self.settings.mt5_tp_points
        if points is None:
            return None
        return price + points if direction == Direction.LONG else price - points

    def _take_profit_for_rr(self, price: float, sl: float, direction: Direction, rr: float) -> float:
        risk_distance = abs(price - sl)
        if risk_distance <= 0:
            raise RuntimeError("Stop-loss distance must be greater than zero")
        if direction == Direction.LONG:
            return price + (risk_distance * rr)
        return price - (risk_distance * rr)

    def _risk_volume(self, price, sl, risk_percent, account_info, symbol_info) -> float:
        equity = getattr(account_info, "equity", None) or getattr(account_info, "balance", None)
        if equity is None or equity <= 0:
            raise RuntimeError("MT5 account equity/balance is unavailable for risk sizing")

        tick_size = getattr(symbol_info, "trade_tick_size", None) or getattr(symbol_info, "point", None)
        tick_value = getattr(symbol_info, "trade_tick_value", None)
        if tick_size is None or tick_size <= 0 or tick_value is None or tick_value <= 0:
            raise RuntimeError("MT5 symbol tick size/value is unavailable for risk sizing")

        stop_distance = abs(price - sl)
        if stop_distance <= 0:
            raise RuntimeError("Stop-loss distance must be greater than zero")

        risk_amount = equity * (risk_percent / 100.0)
        loss_per_lot = (stop_distance / tick_size) * tick_value
        raw_volume = risk_amount / loss_per_lot

        volume_min = getattr(symbol_info, "volume_min", 0.01) or 0.01
        volume_max = getattr(symbol_info, "volume_max", raw_volume) or raw_volume
        volume_step = getattr(symbol_info, "volume_step", 0.01) or 0.01

        stepped = math.floor(raw_volume / volume_step) * volume_step
        bounded = min(max(stepped, volume_min), volume_max)
        decimals = max(0, int(round(-math.log10(volume_step)))) if volume_step < 1 else 0
        return round(bounded, decimals)
