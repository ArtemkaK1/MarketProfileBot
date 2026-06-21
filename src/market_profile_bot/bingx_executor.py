from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from urllib import error, parse, request

from .config import (
    BINGX_BASE_URL,
    BINGX_BALANCE_ENDPOINT,
    BINGX_ENABLE_SL_TP,
    BINGX_LEVERAGE_ENDPOINT,
    BINGX_MARGIN_TYPE_ENDPOINT,
    BINGX_ORDER_ENDPOINT,
    BINGX_RECV_WINDOW,
    BINGX_SIZE_FIELD,
    Settings,
)
from .execution import ExecutionResult
from .models import Direction, TradingViewAlert

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BingXAccountState:
    symbol: str
    balance: Decimal
    available_margin: Decimal | None
    margin_type: str
    long_leverage: Decimal
    short_leverage: Decimal


class BingXExecutor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def execute(self, alert: TradingViewAlert) -> ExecutionResult:
        if alert.direction == Direction.NONE:
            return ExecutionResult("ignored", "IB_READY does not open a position")

        size_usdt = self._calculate_usdt_size(alert)
        if self.settings.dry_run:
            logger.info("DRY_RUN BingX alert: %s", alert.model_dump())
            return ExecutionResult(
                "dry_run",
                (
                    f"{alert.direction} {self.settings.bingx_symbol} "
                    f"{BINGX_SIZE_FIELD}={size_usdt} "
                    f"risk_target={self._risk_amount()} "
                    f"sl={alert.sl} tp={alert.tp}"
                ),
            )

        self._validate_live_settings()
        data = self._place_market_order(alert, size_usdt)
        order_id = _extract_order_id(data)
        return ExecutionResult("filled", "BingX market order submitted", order_id=order_id)

    def current_state(self) -> BingXAccountState:
        """Return the current USDT perpetual-futures state for the configured symbol."""
        self._validate_api_keys()
        common_params = {
            "symbol": self.settings.bingx_symbol,
            "timestamp": int(time.time() * 1000),
            "recvWindow": BINGX_RECV_WINDOW,
        }
        balance_response = self._signed_request(
            "GET",
            BINGX_BALANCE_ENDPOINT,
            {"timestamp": common_params["timestamp"], "recvWindow": BINGX_RECV_WINDOW},
        )
        margin_response = self._signed_request(
            "GET", BINGX_MARGIN_TYPE_ENDPOINT, common_params
        )
        leverage_response = self._signed_request(
            "GET", BINGX_LEVERAGE_ENDPOINT, common_params
        )

        balance_data = _response_data(balance_response).get("balance", {})
        margin_data = _response_data(margin_response)
        leverage_data = _response_data(leverage_response)
        try:
            return BingXAccountState(
                symbol=self.settings.bingx_symbol,
                balance=Decimal(str(balance_data["balance"])),
                available_margin=_optional_decimal(balance_data.get("availableMargin")),
                margin_type=str(margin_data["marginType"]).upper(),
                long_leverage=Decimal(str(leverage_data["longLeverage"])),
                short_leverage=Decimal(str(leverage_data["shortLeverage"])),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("BingX returned an unexpected account-state response") from exc

    def _validate_live_settings(self) -> None:
        missing = []
        if not self.settings.bingx_api_key:
            missing.append("BINGX_API_KEY")
        if not self.settings.bingx_secret_key:
            missing.append("BINGX_SECRET_KEY")
        if not self.settings.bingx_symbol:
            missing.append("BINGX_SYMBOL")
        if self.settings.bingx_initial_capital <= 0:
            missing.append("BINGX_INITIAL_CAPITAL must be > 0")
        if self.settings.bingx_risk_percent <= 0:
            missing.append("BINGX_RISK_PERCENT must be > 0")
        if self.settings.bingx_min_usdt_step <= 0:
            missing.append("BINGX_MIN_USDT_STEP must be > 0")
        if missing:
            raise RuntimeError("Missing BingX configuration: " + ", ".join(missing))

    def _validate_api_keys(self) -> None:
        missing = []
        if not self.settings.bingx_api_key:
            missing.append("BINGX_API_KEY")
        if not self.settings.bingx_secret_key:
            missing.append("BINGX_SECRET_KEY")
        if missing:
            raise RuntimeError("Missing BingX configuration: " + ", ".join(missing))

    def _place_market_order(self, alert: TradingViewAlert, size_usdt: float) -> dict:
        params = self._order_params(alert, size_usdt)
        return self._signed_request("POST", BINGX_ORDER_ENDPOINT, params)

    def _order_params(self, alert: TradingViewAlert, size_usdt: float) -> dict:
        params = {
            "symbol": self.settings.bingx_symbol,
            "side": "BUY" if alert.direction == Direction.LONG else "SELL",
            "positionSide": "LONG" if alert.direction == Direction.LONG else "SHORT",
            "type": "MARKET",
            BINGX_SIZE_FIELD: _number_text(size_usdt),
            "timestamp": int(time.time() * 1000),
            "recvWindow": BINGX_RECV_WINDOW,
        }
        if BINGX_ENABLE_SL_TP and alert.sl is not None:
            params["stopLoss"] = json.dumps(
                {
                    "type": "STOP_MARKET",
                    "stopPrice": alert.sl,
                    "workingType": "MARK_PRICE",
                },
                separators=(",", ":"),
            )
        if BINGX_ENABLE_SL_TP and alert.tp is not None:
            params["takeProfit"] = json.dumps(
                {
                    "type": "TAKE_PROFIT_MARKET",
                    "stopPrice": alert.tp,
                    "workingType": "MARK_PRICE",
                },
                separators=(",", ":"),
            )
        return params

    def _signed_request(self, method: str, path: str, params: dict) -> dict:
        if not self.settings.bingx_secret_key or not self.settings.bingx_api_key:
            raise RuntimeError("BingX API keys are required")
        query = _query_string(params)
        signature = hmac.new(
            self.settings.bingx_secret_key.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        url = f"{BINGX_BASE_URL}{path}?{query}&signature={signature}"
        req = request.Request(url, headers={"X-BX-APIKEY": self.settings.bingx_api_key}, method=method)
        try:
            with request.urlopen(req, timeout=15) as response:
                response_body = response.read().decode("utf-8")
                payload = json.loads(response_body) if response_body else {}
                code = payload.get("code")
                if code not in (None, 0, "0"):
                    message = payload.get("msg") or payload.get("message") or "unknown error"
                    raise RuntimeError(f"BingX request failed: {message} (code {code})")
                return payload
        except error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"BingX request failed: HTTP {exc.code} {body_text}") from exc

    def _calculate_usdt_size(self, alert: TradingViewAlert) -> float:
        if alert.sl is None:
            raise RuntimeError("Cannot calculate BingX size: alert sl is missing")
        entry = Decimal(str(alert.price))
        stop_distance = abs(entry - Decimal(str(alert.sl)))
        if entry <= 0:
            raise RuntimeError("Cannot calculate BingX size: entry price must be > 0")
        if stop_distance <= 0:
            raise RuntimeError("Cannot calculate BingX size: stop distance must be > 0")

        risk_amount = Decimal(str(self._risk_amount()))
        step = Decimal(str(self.settings.bingx_min_usdt_step))
        raw_size = risk_amount * entry / stop_distance
        stepped_size = (raw_size / step).to_integral_value(rounding=ROUND_CEILING) * step
        return float(stepped_size)

    def _risk_amount(self) -> float:
        return self.settings.bingx_initial_capital * self.settings.bingx_risk_percent / 100


def _query_string(params: dict) -> str:
    return parse.urlencode(sorted(params.items()))


def _number_text(value: float) -> str:
    return format(Decimal(str(value)).normalize(), "f")


def _extract_order_id(data: dict) -> int | None:
    value = data.get("data", {}).get("orderId") or data.get("orderId")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _response_data(response: dict) -> dict:
    data = response.get("data", response)
    if not isinstance(data, dict):
        raise RuntimeError("BingX returned an unexpected response")
    return data


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))
