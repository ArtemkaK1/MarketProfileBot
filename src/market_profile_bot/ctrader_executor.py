from __future__ import annotations

import json
import logging
import threading
import time
from urllib import parse, request

from .config import Settings
from .execution import ExecutionResult
from .models import Direction, TradingViewAlert

logger = logging.getLogger(__name__)

_reactor_lock = threading.Lock()
_reactor_started = False


class CTraderExecutor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def execute(self, alert: TradingViewAlert) -> ExecutionResult:
        if alert.direction == Direction.NONE:
            return ExecutionResult("ignored", "IB_READY does not open a position")

        if self.settings.dry_run:
            logger.info("DRY_RUN cTrader alert: %s", alert.model_dump())
            return ExecutionResult(
                "dry_run",
                (
                    f"{alert.direction} {self.settings.ctrader_symbol_name} "
                    f"symbol_id={self.settings.ctrader_symbol_id} "
                    f"volume={self.settings.ctrader_volume} "
                    f"sl={alert.sl} tp={alert.tp}"
                ),
            )

        self._validate_live_settings()
        return self._send_market_order(alert)

    def _validate_live_settings(self) -> None:
        missing = []
        if self.settings.ctrader_host_type not in {"demo", "live"}:
            missing.append("CTRADER_HOST_TYPE must be demo or live")
        if not self.settings.ctrader_client_id:
            missing.append("CTRADER_CLIENT_ID")
        if not self.settings.ctrader_client_secret:
            missing.append("CTRADER_CLIENT_SECRET")
        if not self.settings.ctrader_access_token:
            missing.append("CTRADER_ACCESS_TOKEN")
        if self.settings.ctrader_account_id is None:
            missing.append("CTRADER_ACCOUNT_ID")
        if self.settings.ctrader_symbol_id is None:
            missing.append("CTRADER_SYMBOL_ID")
        if self.settings.ctrader_volume <= 0:
            missing.append("CTRADER_VOLUME must be > 0")
        if missing:
            raise RuntimeError("Missing cTrader configuration: " + ", ".join(missing))

    def _validate_app_settings(self) -> None:
        missing = []
        if self.settings.ctrader_host_type not in {"demo", "live"}:
            missing.append("CTRADER_HOST_TYPE must be demo or live")
        if not self.settings.ctrader_client_id:
            missing.append("CTRADER_CLIENT_ID")
        if not self.settings.ctrader_client_secret:
            missing.append("CTRADER_CLIENT_SECRET")
        if missing:
            raise RuntimeError("Missing cTrader configuration: " + ", ".join(missing))

    def _validate_access_settings(self) -> None:
        self._validate_app_settings()
        if not self.settings.ctrader_access_token:
            raise RuntimeError("Missing cTrader configuration: CTRADER_ACCESS_TOKEN")

    def list_accounts(self) -> list[dict]:
        self._validate_access_settings()

        from ctrader_open_api.messages.OpenApiMessages_pb2 import (
            ProtoOAGetAccountListByAccessTokenReq,
            ProtoOAGetAccountListByAccessTokenRes,
        )

        def request_accounts(send):
            account_req = ProtoOAGetAccountListByAccessTokenReq()
            account_req.accessToken = self.settings.ctrader_access_token
            response = send(account_req)
            if not isinstance(response, ProtoOAGetAccountListByAccessTokenRes):
                raise RuntimeError(f"Unexpected cTrader response: {response}")
            return [
                {
                    "ctidTraderAccountId": int(account.ctidTraderAccountId),
                    "isLive": bool(account.isLive),
                    "traderLogin": int(account.traderLogin),
                }
                for account in response.ctidTraderAccount
            ]

        return self._with_authenticated_app(request_accounts)

    def list_symbols(self, query: str | None = None) -> list[dict]:
        self._validate_access_settings()
        if self.settings.ctrader_account_id is None:
            raise RuntimeError("Missing cTrader configuration: CTRADER_ACCOUNT_ID")

        from ctrader_open_api.messages.OpenApiMessages_pb2 import (
            ProtoOAAccountAuthReq,
            ProtoOASymbolsListReq,
            ProtoOASymbolsListRes,
        )

        def request_symbols(send):
            account_auth = ProtoOAAccountAuthReq()
            account_auth.ctidTraderAccountId = self.settings.ctrader_account_id
            account_auth.accessToken = self.settings.ctrader_access_token
            send(account_auth)

            symbols_req = ProtoOASymbolsListReq()
            symbols_req.ctidTraderAccountId = self.settings.ctrader_account_id
            response = send(symbols_req)
            if not isinstance(response, ProtoOASymbolsListRes):
                raise RuntimeError(f"Unexpected cTrader response: {response}")

            needle = query.lower() if query else ""
            symbols = []
            for symbol in response.symbol:
                name = symbol.symbolName
                description = symbol.description
                if needle and needle not in name.lower() and needle not in description.lower():
                    continue
                symbols.append(
                    {
                        "symbolId": int(symbol.symbolId),
                        "symbolName": name,
                        "description": description,
                        "enabled": bool(symbol.enabled),
                    }
                )
            return symbols

        return self._with_authenticated_app(request_symbols)

    def _with_authenticated_app(self, callback):
        from ctrader_open_api import Client, EndPoints, Protobuf, TcpProtocol
        from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAApplicationAuthReq
        from twisted.internet import threads

        reactor = _ensure_reactor()
        host = (
            EndPoints.PROTOBUF_LIVE_HOST
            if self.settings.ctrader_host_type == "live"
            else EndPoints.PROTOBUF_DEMO_HOST
        )
        client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)

        def send(message, timeout=10):
            envelope = threads.blockingCallFromThread(
                reactor,
                lambda: client.send(message, responseTimeoutInSeconds=timeout),
            )
            return Protobuf.extract(envelope)

        threads.blockingCallFromThread(reactor, client.startService)
        try:
            app_auth = ProtoOAApplicationAuthReq()
            app_auth.clientId = self.settings.ctrader_client_id
            app_auth.clientSecret = self.settings.ctrader_client_secret
            send(app_auth)
            return callback(send)
        finally:
            threads.blockingCallFromThread(reactor, client.stopService)

    def _send_market_order(self, alert: TradingViewAlert) -> ExecutionResult:
        from ctrader_open_api.messages.OpenApiMessages_pb2 import (
            ProtoOAAccountAuthReq,
            ProtoOAExecutionEvent,
            ProtoOANewOrderReq,
            ProtoOAOrderType,
            ProtoOATradeSide,
        )

        def send_order(send):
            account_auth = ProtoOAAccountAuthReq()
            account_auth.ctidTraderAccountId = self.settings.ctrader_account_id
            account_auth.accessToken = self.settings.ctrader_access_token
            send(account_auth)

            order_req = ProtoOANewOrderReq()
            order_req.ctidTraderAccountId = self.settings.ctrader_account_id
            order_req.symbolId = self.settings.ctrader_symbol_id
            order_req.orderType = ProtoOAOrderType.MARKET
            order_req.tradeSide = (
                ProtoOATradeSide.BUY if alert.direction == Direction.LONG else ProtoOATradeSide.SELL
            )
            order_req.volume = self.settings.ctrader_volume
            order_req.slippageInPoints = self.settings.ctrader_slippage_points
            order_req.label = "pre-nyse-ib"
            order_req.comment = f"{alert.type} {alert.id}"[:100]
            if alert.sl is not None:
                order_req.stopLoss = alert.sl
            if alert.tp is not None:
                order_req.takeProfit = alert.tp

            response = send(order_req, timeout=15)
            if not isinstance(response, ProtoOAExecutionEvent):
                raise RuntimeError(f"Unexpected cTrader response: {response}")
            if response.errorCode:
                raise RuntimeError(f"cTrader order failed: {response.errorCode}")

            order_id = None
            if response.HasField("order"):
                order_id = int(response.order.orderId)
            elif response.HasField("deal"):
                order_id = int(response.deal.orderId)
            return ExecutionResult("filled", "cTrader market order opened", order_id=order_id)

        return self._with_authenticated_app(send_order)


def _ensure_reactor():
    global _reactor_started
    from twisted.internet import reactor

    with _reactor_lock:
        if not _reactor_started:
            thread = threading.Thread(
                target=reactor.run,
                kwargs={"installSignalHandlers": False},
                daemon=True,
            )
            thread.start()
            while not reactor.running:
                time.sleep(0.01)
            _reactor_started = True
    return reactor


def ctrader_auth_url(settings: Settings) -> str:
    if not settings.ctrader_client_id:
        raise RuntimeError("CTRADER_CLIENT_ID is required")
    if not settings.ctrader_redirect_uri:
        raise RuntimeError("CTRADER_REDIRECT_URI is required")

    query = parse.urlencode(
        {
            "client_id": settings.ctrader_client_id,
            "redirect_uri": settings.ctrader_redirect_uri,
            "scope": "trading",
            "product": "web",
        }
    )
    return f"https://id.ctrader.com/my/settings/openapi/grantingaccess/?{query}"


def exchange_authorization_code(settings: Settings, code: str) -> dict:
    if not settings.ctrader_client_id:
        raise RuntimeError("CTRADER_CLIENT_ID is required")
    if not settings.ctrader_client_secret:
        raise RuntimeError("CTRADER_CLIENT_SECRET is required")
    if not settings.ctrader_redirect_uri:
        raise RuntimeError("CTRADER_REDIRECT_URI is required")

    return _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.ctrader_redirect_uri,
            "client_id": settings.ctrader_client_id,
            "client_secret": settings.ctrader_client_secret,
        },
        method="GET",
    )


def refresh_access_token(settings: Settings) -> dict:
    if not settings.ctrader_client_id:
        raise RuntimeError("CTRADER_CLIENT_ID is required")
    if not settings.ctrader_client_secret:
        raise RuntimeError("CTRADER_CLIENT_SECRET is required")
    if not settings.ctrader_refresh_token:
        raise RuntimeError("CTRADER_REFRESH_TOKEN is required")

    return _token_request(
        {
            "grant_type": "refresh_token",
            "refresh_token": settings.ctrader_refresh_token,
            "client_id": settings.ctrader_client_id,
            "client_secret": settings.ctrader_client_secret,
        },
        method="POST",
    )


def _token_request(params: dict, method: str) -> dict:
    query = parse.urlencode(params)
    req = request.Request(
        f"https://openapi.ctrader.com/apps/token?{query}",
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method=method,
    )
    with request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))
