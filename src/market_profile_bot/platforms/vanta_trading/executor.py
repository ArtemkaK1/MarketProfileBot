from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from decimal import Decimal, InvalidOperation
from urllib import error, request

from ...config import Settings
from ...execution import ExecutionResult
from ...models import Direction, TradingViewAlert
from ...trading import (
    AccountState,
    TradeSizing,
    adjust_trade_levels,
    calculate_quote_order_qty,
    number_text,
)

logger = logging.getLogger(__name__)

VANTA_ACCOUNT_ENDPOINT = "/api/v1/trading/account"
VANTA_POSITIONS_ENDPOINT = "/api/v1/trading/positions"
VANTA_ORDERS_ENDPOINT = "/api/v1/trading/orders"


class VantaTradingExecutor:
    platform_name = "vanta_trading"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def execute(self, alert: TradingViewAlert) -> ExecutionResult:
        if alert.direction == Direction.NONE:
            return ExecutionResult("ignored", "IB_READY does not open a position")

        self._validate_execution_settings()
        execution_alert = adjust_trade_levels(
            alert, self.settings.sl_tp_offset_points
        )
        account = self.current_state()
        sizing = self._calculate_trade_sizing(execution_alert, account)
        order_body = self._order_body(execution_alert, sizing)

        if self.settings.dry_run:
            cap_note = (
                " · capped_by_buying_power=true"
                if sizing.capped_by_buying_power
                else ""
            )
            logger.info("DRY_RUN VantaTrading alert: %s", alert.model_dump())
            return ExecutionResult(
                "dry_run",
                (
                    f"VantaTrading order prepared · {execution_alert.direction} "
                    f"{self.settings.vanta_symbol} · balance={number_text(sizing.balance)} USDC · "
                    f"buying_power={number_text(account.buying_power or sizing.balance)} USDC · "
                    f"risk_target={number_text(sizing.target_risk_amount or sizing.risk_amount)} USDC · "
                    f"risk_actual={number_text(sizing.risk_amount)} USDC · "
                    f"value={number_text(sizing.quote_order_qty)} USDC · "
                    f"sl={execution_alert.sl} · tp={execution_alert.tp}"
                    f"{cap_note}"
                ),
            )

        self._ensure_no_open_position()
        data = self._signed_request("POST", VANTA_ORDERS_ENDPOINT, order_body)
        order_id = _extract_order_id(data)
        return ExecutionResult(
            "filled", "VantaTrading market order submitted", order_id=order_id
        )

    def current_state(self) -> AccountState:
        self._validate_api_keys()
        data = self._signed_request("GET", VANTA_ACCOUNT_ENDPOINT)
        payload = _response_data(data)
        balance = _first_decimal(
            payload,
            "balance",
            "equity",
            "currentBalance",
            "currentEquity",
            "accountBalance",
            "cashBalance",
            "initialBalance",
            default=Decimal(str(self.settings.vanta_account_balance)),
        )
        if balance <= 0:
            raise RuntimeError("VantaTrading account balance must be greater than zero")
        leverage = _first_decimal(
            payload,
            "leverage",
            "accountLeverage",
            default=Decimal(str(self.settings.vanta_leverage)),
        )
        buying_power = _first_decimal(
            payload,
            "buyingPower",
            "buying_power",
            "availableBuyingPower",
            default=balance * leverage,
        )
        available_margin = _first_decimal(
            payload,
            "availableMargin",
            "available_margin",
            "availableBalance",
            default=buying_power,
        )
        return AccountState(
            platform="VantaTrading",
            symbol=self.settings.vanta_symbol,
            balance=balance,
            buying_power=buying_power,
            available_margin=available_margin,
            leverage=leverage,
            currency="USDC",
        )

    def _validate_execution_settings(self) -> None:
        missing = []
        if not self.settings.vanta_account_id:
            missing.append("VANTA_ACCOUNT_ID")
        if not self.settings.vanta_symbol:
            missing.append("VANTA_SYMBOL")
        if self.settings.risk_percent <= 0 or self.settings.risk_percent > 100:
            missing.append("RISK_PERCENT must be > 0 and <= 100")
        if self.settings.min_quote_step <= 0:
            missing.append("MIN_QUOTE_STEP must be > 0")
        if self.settings.max_notional_usdc is not None and self.settings.max_notional_usdc <= 0:
            missing.append("MAX_NOTIONAL_USDC must be > 0")
        if self.settings.sl_tp_offset_points < 0:
            missing.append("SL_TP_OFFSET_POINTS must be >= 0")
        self._validate_api_keys(missing)

    def _validate_api_keys(self, missing: list[str] | None = None) -> None:
        missing = [] if missing is None else missing
        if not self.settings.vanta_key_id:
            missing.append("VANTA_KEY_ID")
        if not self.settings.vanta_secret:
            missing.append("VANTA_SECRET")
        if missing:
            raise RuntimeError("Missing VantaTrading configuration: " + ", ".join(missing))

    def _calculate_trade_sizing(
        self, alert: TradingViewAlert, account: AccountState
    ) -> TradeSizing:
        max_notional = (
            Decimal(str(self.settings.max_notional_usdc))
            if self.settings.max_notional_usdc is not None
            else None
        )
        return calculate_quote_order_qty(
            alert,
            balance=account.balance,
            buying_power=account.buying_power,
            risk_percent=self.settings.risk_percent,
            min_quote_step=self.settings.min_quote_step,
            max_notional=max_notional,
            platform_name="VantaTrading",
        )

    def _order_body(self, alert: TradingViewAlert, sizing: TradeSizing) -> dict:
        trade = {
            "execution_type": "MARKET",
            "trade_pair": _api_trade_pair(self.settings.vanta_symbol),
            "order_type": "LONG" if alert.direction == Direction.LONG else "SHORT",
            "value": float(sizing.quote_order_qty),
        }
        if alert.sl is not None:
            trade["stop_loss"] = alert.sl
        if alert.tp is not None:
            trade["take_profit"] = alert.tp
        return {
            "accountId": self.settings.vanta_account_id,
            "trade": trade,
        }

    def _ensure_no_open_position(self) -> None:
        response = self._signed_request("GET", VANTA_POSITIONS_ENDPOINT)
        positions = _list_response_data(response)
        for position in positions:
            if not isinstance(position, dict):
                continue
            symbol = str(
                position.get("trade_pair")
                or position.get("symbol")
                or position.get("instrument")
                or ""
            )
            if symbol and _api_trade_pair(symbol) != _api_trade_pair(self.settings.vanta_symbol):
                continue
            amount = _first_decimal(
                position,
                "value",
                "quantity",
                "size",
                "positionSize",
                default=Decimal("0"),
            )
            status = str(position.get("status", "")).upper()
            if amount != 0 and status not in {"CLOSED", "CANCELED", "CANCELLED"}:
                raise RuntimeError(
                    f"An open VantaTrading position already exists for {self.settings.vanta_symbol}"
                )

    def _signed_request(
        self, method: str, path: str, body: dict | None = None
    ) -> dict | list:
        if not self.settings.vanta_key_id or not self.settings.vanta_secret:
            raise RuntimeError("VantaTrading API keys are required")
        body_bytes = b""
        headers = {
            "X-Vanta-Key-Id": self.settings.vanta_key_id,
        }
        if body is not None:
            body_bytes = json.dumps(body, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"

        ts = str(int(time.time() * 1000))
        nonce = secrets.token_hex(16)
        body_hash = hashlib.sha256(body_bytes).hexdigest()
        canonical = f"v1\n{method}\n{path}\n{ts}\n{nonce}\n{body_hash}"
        signature = base64.b64encode(
            hmac.new(
                self.settings.vanta_secret.encode("utf-8"),
                canonical.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        ).decode("ascii")
        headers.update(
            {
                "X-Vanta-Timestamp": ts,
                "X-Vanta-Nonce": nonce,
                "X-Vanta-Signature": f"v1={signature}",
            }
        )

        req = request.Request(
            f"{self.settings.vanta_base_url.rstrip('/')}{path}",
            data=body_bytes if body is not None else None,
            headers=headers,
            method=method,
        )
        try:
            with request.urlopen(req, timeout=15) as response:
                response_body = response.read().decode("utf-8")
                return json.loads(response_body) if response_body else {}
        except error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"VantaTrading request failed: HTTP {exc.code} {body_text}"
            ) from exc


def _response_data(response: dict | list) -> dict:
    if isinstance(response, dict):
        data = response.get("data", response)
        if isinstance(data, dict) and isinstance(data.get("account"), dict):
            return data["account"]
        if isinstance(data, dict):
            return data
    raise RuntimeError("VantaTrading returned an unexpected response")


def _list_response_data(response: dict | list) -> list:
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        data = response.get("data", response.get("positions", response))
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            positions = data.get("positions")
            if isinstance(positions, list):
                return positions
    raise RuntimeError("VantaTrading returned an unexpected positions response")


def _first_decimal(
    values: dict, *keys: str, default: Decimal | None = None
) -> Decimal:
    for key in keys:
        if key not in values or values[key] is None:
            continue
        try:
            return _decimal_value(values[key])
        except (InvalidOperation, TypeError, ValueError):
            if default is not None:
                continue
            raise RuntimeError(
                f"VantaTrading returned an unexpected decimal value for {key}"
            )
    if default is not None:
        return default
    raise RuntimeError("VantaTrading returned an unexpected account response")


def _api_trade_pair(symbol: str) -> str:
    return "".join(char for char in symbol.upper() if char.isalnum())


def _decimal_value(value: object) -> Decimal:
    if isinstance(value, dict):
        for key in ("value", "amount", "balance", "total", "available"):
            if key in value and value[key] is not None:
                return _decimal_value(value[key])
        raise ValueError("decimal object has no known numeric field")
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if "current" in text.lower() and "max" in text.lower():
            raise ValueError("display-only leverage string")
        matches = re.findall(r"-?\d+(?:\.\d+)?", text)
        if not matches:
            raise ValueError("decimal string has no numeric value")
        return Decimal(matches[-1] if ":" in text else matches[0])
    return Decimal(str(value))


def _extract_order_id(data: dict | list) -> int | None:
    if not isinstance(data, dict):
        return None
    payload = data.get("data", data)
    if not isinstance(payload, dict):
        return None
    value = payload.get("orderId") or payload.get("order_id") or payload.get("id")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
