from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from urllib import error, parse, request

from .config import (
    BINGX_BASE_URL,
    BINGX_BALANCE_ENDPOINT,
    BINGX_CONTRACTS_ENDPOINT,
    BINGX_ENABLE_SL_TP,
    BINGX_FULL_ORDER_ENDPOINT,
    BINGX_LEVERAGE_ENDPOINT,
    BINGX_MARGIN_TYPE_ENDPOINT,
    BINGX_ORDER_ENDPOINT,
    BINGX_POSITION_MODE_ENDPOINT,
    BINGX_POSITIONS_ENDPOINT,
    BINGX_RECV_WINDOW,
    BINGX_SIZE_FIELD,
    BINGX_TEST_ORDER_ENDPOINT,
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


@dataclass(frozen=True)
class TradeSizing:
    balance: Decimal
    risk_amount: Decimal
    quote_order_qty: Decimal


class BingXExecutor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._resolved_symbol: str | None = None

    def execute(self, alert: TradingViewAlert) -> ExecutionResult:
        if alert.direction == Direction.NONE:
            return ExecutionResult("ignored", "IB_READY does not open a position")

        self._validate_execution_settings()
        execution_alert = adjust_trade_levels(
            alert, self.settings.bingx_sl_tp_offset_points
        )
        sizing = self._calculate_trade_sizing(execution_alert, self._fetch_balance())
        api_symbol = self._resolve_symbol()
        position_side = self._position_side(execution_alert.direction)
        params = self._order_params(
            execution_alert,
            sizing.quote_order_qty,
            symbol=api_symbol,
            position_side=position_side,
            client_order_id=_client_order_id(alert.id),
        )
        test_params = dict(params)
        test_params["clientOrderId"] = _client_order_id(alert.id, test=True)
        self._signed_request("POST", BINGX_TEST_ORDER_ENDPOINT, test_params)

        if self.settings.dry_run:
            logger.info("DRY_RUN BingX alert: %s", alert.model_dump())
            return ExecutionResult(
                "dry_run",
                (
                    f"BingX test order accepted · {execution_alert.direction} "
                    f"{self.settings.bingx_symbol} · balance={_number_text(sizing.balance)} USDT · "
                    f"risk_target={_number_text(sizing.risk_amount)} USDT · "
                    f"{BINGX_SIZE_FIELD}={_number_text(sizing.quote_order_qty)} USDT · "
                    f"sl={execution_alert.sl} · tp={execution_alert.tp}"
                ),
            )

        self._ensure_no_open_position(api_symbol)
        self._ensure_no_strategy_order_today(alert, api_symbol)
        params["timestamp"] = int(time.time() * 1000)
        data = self._place_market_order(params)
        order_id = _extract_order_id(data)
        return ExecutionResult("filled", "BingX market order submitted", order_id=order_id)

    def current_state(self) -> BingXAccountState:
        """Return the current USDT perpetual-futures state for the configured symbol."""
        self._validate_api_keys()
        api_symbol = self._resolve_symbol()
        common_params = {
            "symbol": api_symbol,
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
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("BingX returned an unexpected account-state response") from exc

    def _validate_execution_settings(self) -> None:
        missing = []
        if not self.settings.bingx_api_key:
            missing.append("BINGX_API_KEY")
        if not self.settings.bingx_secret_key:
            missing.append("BINGX_SECRET_KEY")
        if not self.settings.bingx_symbol:
            missing.append("BINGX_SYMBOL")
        if not 0 < self.settings.bingx_risk_percent <= 100:
            missing.append("BINGX_RISK_PERCENT must be > 0 and <= 100")
        if self.settings.bingx_min_usdt_step <= 0:
            missing.append("BINGX_MIN_USDT_STEP must be > 0")
        if self.settings.bingx_max_notional_usdt <= 0:
            missing.append("BINGX_MAX_NOTIONAL_USDT must be > 0")
        if self.settings.bingx_sl_tp_offset_points < 0:
            missing.append("BINGX_SL_TP_OFFSET_POINTS must be >= 0")
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

    def _place_market_order(self, params: dict) -> dict:
        return self._signed_request("POST", BINGX_ORDER_ENDPOINT, params)

    def _fetch_balance(self) -> Decimal:
        balance_data = self._fetch_balance_data()
        try:
            balance = Decimal(str(balance_data["balance"]))
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("BingX returned an unexpected balance response") from exc
        if balance <= 0:
            raise RuntimeError("BingX USDT futures balance must be greater than zero")
        return balance

    def _fetch_balance_data(self) -> dict:
        response = self._signed_request(
            "GET",
            BINGX_BALANCE_ENDPOINT,
            {"timestamp": int(time.time() * 1000), "recvWindow": BINGX_RECV_WINDOW},
        )
        balance_data = _response_data(response).get("balance", {})
        if not isinstance(balance_data, dict):
            raise RuntimeError("BingX returned an unexpected balance response")
        return balance_data

    def _position_side(self, direction: Direction) -> str:
        response = self._signed_request(
            "GET",
            BINGX_POSITION_MODE_ENDPOINT,
            {"timestamp": int(time.time() * 1000), "recvWindow": BINGX_RECV_WINDOW},
        )
        value = _response_data(response).get("dualSidePosition")
        if isinstance(value, bool):
            dual_side = value
        elif isinstance(value, str) and value.lower() in {"true", "false"}:
            dual_side = value.lower() == "true"
        else:
            raise RuntimeError("BingX returned an unexpected position-mode response")
        if not dual_side:
            return "BOTH"
        return "LONG" if direction == Direction.LONG else "SHORT"

    def _ensure_no_open_position(self, symbol: str) -> None:
        response = self._signed_request(
            "GET",
            BINGX_POSITIONS_ENDPOINT,
            {
                "symbol": symbol,
                "timestamp": int(time.time() * 1000),
                "recvWindow": BINGX_RECV_WINDOW,
            },
        )
        positions = response.get("data", [])
        if not isinstance(positions, list):
            raise RuntimeError("BingX returned an unexpected positions response")
        for position in positions:
            if not isinstance(position, dict):
                continue
            try:
                amount = Decimal(str(position.get("positionAmt", "0")))
            except (InvalidOperation, ValueError) as exc:
                raise RuntimeError("BingX returned an unexpected positions response") from exc
            if amount != 0:
                raise RuntimeError(
                    f"An open BingX position already exists for {self.settings.bingx_symbol}"
                )

    def _ensure_no_strategy_order_today(
        self, alert: TradingViewAlert, symbol: str
    ) -> None:
        local_time = alert.time.astimezone(self.settings.timezone)
        day_start = local_time.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start.replace(hour=23, minute=59, second=59, microsecond=999000)
        response = self._signed_request(
            "GET",
            BINGX_FULL_ORDER_ENDPOINT,
            {
                "symbol": symbol,
                "startTime": int(day_start.timestamp() * 1000),
                "endTime": int(day_end.timestamp() * 1000),
                "limit": 1000,
                "timestamp": int(time.time() * 1000),
                "recvWindow": BINGX_RECV_WINDOW,
            },
        )
        data = _response_data(response)
        orders = data.get("orders", [])
        if not isinstance(orders, list):
            raise RuntimeError("BingX returned an unexpected order-history response")
        if any(
            isinstance(order, dict)
            and str(order.get("clientOrderId", "")).lower().startswith("mpb-")
            for order in orders
        ):
            raise RuntimeError("A strategy order has already been placed for this market day")

    def _resolve_symbol(self) -> str:
        if self._resolved_symbol is not None:
            return self._resolved_symbol

        configured_symbol = self.settings.bingx_symbol.strip().upper()
        response = self._public_request(BINGX_CONTRACTS_ENDPOINT)
        contracts = response.get("data")
        if not isinstance(contracts, list):
            raise RuntimeError("BingX returned an unexpected contracts response")

        for contract in contracts:
            if not isinstance(contract, dict):
                continue
            api_symbol = str(contract.get("symbol", "")).upper()
            display_name = str(contract.get("displayName", "")).upper()
            currency = str(contract.get("currency", "")).upper()
            display_base = _without_settlement_currency(display_name)
            is_usdt_display_alias = (
                currency == "USDT" and configured_symbol == display_base
            )
            if configured_symbol in {api_symbol, display_name} or is_usdt_display_alias:
                self._resolved_symbol = api_symbol
                if api_symbol != configured_symbol:
                    logger.info(
                        "Resolved BingX display symbol %s to API symbol %s",
                        self.settings.bingx_symbol,
                        api_symbol,
                    )
                return api_symbol

        raise RuntimeError(
            f"BingX futures symbol '{self.settings.bingx_symbol}' was not found"
        )

    def _public_request(self, path: str) -> dict:
        req = request.Request(
            f"{BINGX_BASE_URL}{path}",
            headers={"X-SOURCE-KEY": "BX-AI-SKILL"},
            method="GET",
        )
        try:
            with request.urlopen(req, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"BingX request failed: HTTP {exc.code} {body_text}") from exc

        code = payload.get("code")
        if code not in (None, 0, "0"):
            message = payload.get("msg") or payload.get("message") or "unknown error"
            raise RuntimeError(f"BingX request failed: {message} (code {code})")
        return payload

    def _order_params(
        self,
        alert: TradingViewAlert,
        quote_order_qty: Decimal,
        *,
        symbol: str,
        position_side: str,
        client_order_id: str,
    ) -> dict:
        params = {
            "symbol": symbol,
            "side": "BUY" if alert.direction == Direction.LONG else "SELL",
            "positionSide": position_side,
            "type": "MARKET",
            BINGX_SIZE_FIELD: _number_text(quote_order_qty),
            "clientOrderId": client_order_id,
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
        canonical = _query_string(params)
        signature = hmac.new(
            self.settings.bingx_secret_key.encode("utf-8"),
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        headers = {
            "X-BX-APIKEY": self.settings.bingx_api_key,
            "X-SOURCE-KEY": "BX-AI-SKILL",
        }
        body = None
        if method == "POST":
            url = f"{BINGX_BASE_URL}{path}"
            body = f"{canonical}&signature={signature}".encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            query = _request_query_string(params)
            url = f"{BINGX_BASE_URL}{path}?{query}&signature={signature}"
        req = request.Request(url, data=body, headers=headers, method=method)
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

    def _calculate_trade_sizing(
        self, alert: TradingViewAlert, balance: Decimal
    ) -> TradeSizing:
        if alert.sl is None:
            raise RuntimeError("Cannot calculate BingX size: alert sl is missing")
        entry = Decimal(str(alert.price))
        stop_distance = abs(entry - Decimal(str(alert.sl)))
        if entry <= 0:
            raise RuntimeError("Cannot calculate BingX size: entry price must be > 0")
        if stop_distance <= 0:
            raise RuntimeError("Cannot calculate BingX size: stop distance must be > 0")

        if balance <= 0:
            raise RuntimeError("Cannot calculate BingX size: balance must be > 0")
        risk_amount = balance * Decimal(str(self.settings.bingx_risk_percent)) / Decimal("100")
        step = Decimal(str(self.settings.bingx_min_usdt_step))
        raw_notional = risk_amount * entry / stop_distance
        quote_order_qty = (
            raw_notional / step
        ).to_integral_value(rounding=ROUND_FLOOR) * step
        if quote_order_qty <= 0:
            raise RuntimeError("Calculated BingX notional is below the configured USDT step")
        max_notional = Decimal(str(self.settings.bingx_max_notional_usdt))
        if quote_order_qty > max_notional:
            raise RuntimeError(
                f"Calculated BingX notional {_number_text(quote_order_qty)} USDT exceeds "
                f"BINGX_MAX_NOTIONAL_USDT={_number_text(max_notional)}"
            )
        return TradeSizing(
            balance=balance,
            risk_amount=risk_amount,
            quote_order_qty=quote_order_qty,
        )


def _query_string(params: dict) -> str:
    return "&".join(f"{key}={params[key]}" for key in sorted(params))


def _request_query_string(params: dict) -> str:
    pairs = []
    for key in sorted(params):
        value = str(params[key])
        if "[" in value or "{" in value:
            value = parse.quote(value, safe="")
        pairs.append(f"{key}={value}")
    return "&".join(pairs)


def _number_text(value: float | Decimal) -> str:
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


def _without_settlement_currency(symbol: str) -> str:
    for suffix in ("-USDT", "-USDC"):
        if symbol.endswith(suffix):
            return symbol[: -len(suffix)]
    return symbol


def _client_order_id(alert_id: str, *, test: bool = False) -> str:
    prefix = "mpbt" if test else "mpb"
    digest = hashlib.sha256(alert_id.encode("utf-8")).hexdigest()
    return f"{prefix}-{digest[: 40 - len(prefix) - 1]}"


def adjust_trade_levels(
    alert: TradingViewAlert, offset_points: float
) -> TradingViewAlert:
    if alert.direction == Direction.NONE or offset_points == 0:
        return alert
    if alert.sl is None or alert.tp is None:
        raise RuntimeError("Cannot adjust BingX levels: alert sl or tp is missing")
    offset = float(offset_points)
    if alert.direction == Direction.LONG:
        sl = alert.sl - offset
        tp = alert.tp + offset
    else:
        sl = alert.sl + offset
        tp = alert.tp - offset
    return alert.model_copy(update={"sl": sl, "tp": tp})
