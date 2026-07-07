from datetime import time
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from market_profile_bot.app import _create_executor, create_app
from market_profile_bot.config import Settings
from market_profile_bot.execution import ExecutionResult
from market_profile_bot.models import TradingViewAlert
from market_profile_bot.platforms.bingx import BingXExecutor
from market_profile_bot.platforms.vanta_trading import VantaTradingExecutor
from market_profile_bot.telegram import TelegramNotifier
from market_profile_bot.trading import AccountState


def settings() -> Settings:
    return Settings(
        webhook_secret="secret",
        trading_platform="vanta_trading",
        vanta_key_id="key",
        vanta_secret="secret",
        vanta_account_id="bba0bc1c-7cb1-494c-b32b-fa64277e1cfb",
        vanta_base_url="https://app.vantatrading.io",
        vanta_symbol="XYZ100/USDC",
        vanta_account_balance=5000,
        vanta_leverage=1.5,
        risk_percent=1,
        min_quote_step=0.01,
        max_notional_usdc=None,
        sl_tp_offset_points=0,
        bingx_api_key="key",
        bingx_secret_key="secret",
        bingx_symbol="NASDAQ100-USDT",
        bingx_risk_percent=5,
        bingx_min_usdt_step=0.01,
        bingx_max_notional_usdt=1000,
        bingx_sl_tp_offset_points=2.5,
        dry_run=True,
        auto_trade=False,
        timezone=ZoneInfo("America/New_York"),
        entry_cutoff=time(16, 0),
        telegram_bot_token="token",
        telegram_chat_id="123",
        telegram_enabled=True,
    )


def live_settings() -> Settings:
    return settings().__class__(
        **{**settings().__dict__, "dry_run": False, "auto_trade": True}
    )


def test_executor_factory_defaults_to_vanta():
    assert isinstance(_create_executor(settings()), VantaTradingExecutor)


def test_executor_factory_supports_bingx():
    bingx_settings = settings().__class__(
        **{**settings().__dict__, "trading_platform": "bingx"}
    )

    assert isinstance(_create_executor(bingx_settings), BingXExecutor)


def test_state_command_replies_only_to_configured_chat(monkeypatch):
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: settings()))
    monkeypatch.setattr(
        VantaTradingExecutor,
        "current_state",
        lambda self: AccountState(
            platform="VantaTrading",
            symbol="XYZ100/USDC",
            balance=Decimal("123.45"),
            buying_power=Decimal("185.175"),
            available_margin=Decimal("100"),
            leverage=Decimal("1.5"),
            currency="USDC",
        ),
    )
    sent = []
    monkeypatch.setattr(
        TelegramNotifier,
        "send",
        lambda self, text, **kwargs: sent.append((text, kwargs.get("chat_id"))),
    )
    client = TestClient(create_app())

    allowed = client.post(
        "/telegram/webhook",
        json={"message": {"chat": {"id": 123}, "text": "/vanta_state"}},
    )
    denied = client.post(
        "/telegram/webhook",
        json={"message": {"chat": {"id": 999}, "text": "/vanta_state"}},
    )

    assert allowed.json() == {"status": "ok"}
    assert denied.json() == {"status": "ignored"}
    assert len(sent) == 1
    assert "Balance: 123.45 USDC" in sent[0][0]
    assert sent[0][1] == "123"


def test_vanta_test_position_command_forces_dry_run_executor(monkeypatch):
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: live_settings()))
    seen = []

    def execute(self, alert: TradingViewAlert):
        seen.append((self.settings.dry_run, alert))
        return ExecutionResult("dry_run", "prepared test order")

    monkeypatch.setattr(VantaTradingExecutor, "execute", execute)
    sent = []
    monkeypatch.setattr(
        TelegramNotifier,
        "send",
        lambda self, text, **kwargs: sent.append((text, kwargs.get("chat_id"))),
    )
    client = TestClient(create_app())

    response = client.post(
        "/telegram/webhook",
        json={"message": {"chat": {"id": 123}, "text": "/vanta_test_position LONG 20000 19900 20100"}},
    )

    assert response.json() == {"status": "dry_run", "detail": "prepared test order"}
    assert seen[0][0] is True
    assert seen[0][1].direction == "LONG"
    assert seen[0][1].price == 20000
    assert seen[0][1].sl == 19900
    assert seen[0][1].tp == 20100
    assert any("Dry Run" in text for text, _chat_id in sent)


def test_bingx_state_command_uses_bingx_executor(monkeypatch):
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: settings()))
    monkeypatch.setattr(
        BingXExecutor,
        "current_state",
        lambda self: AccountState(
            platform="BingX USDT Futures",
            symbol="NASDAQ100-USDT",
            balance=Decimal("123.45"),
            available_margin=Decimal("100"),
            margin_type="CROSSED",
            long_leverage=Decimal("10"),
            short_leverage=Decimal("5"),
            currency="USDT",
        ),
    )
    sent = []
    monkeypatch.setattr(
        TelegramNotifier,
        "send",
        lambda self, text, **kwargs: sent.append((text, kwargs.get("chat_id"))),
    )
    client = TestClient(create_app())

    response = client.post(
        "/telegram/webhook",
        json={"message": {"chat": {"id": 123}, "text": "/bingx_state"}},
    )

    assert response.json() == {"status": "ok"}
    assert "BingX USDT Futures" in sent[0][0]
    assert "Balance: 123.45 USDT" in sent[0][0]


def test_bingx_test_position_command_forces_dry_run_executor(monkeypatch):
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: live_settings()))
    seen = []

    def execute(self, alert: TradingViewAlert):
        seen.append((self.settings.trading_platform, self.settings.dry_run, alert))
        return ExecutionResult("dry_run", "prepared bingx test order")

    monkeypatch.setattr(BingXExecutor, "execute", execute)
    sent = []
    monkeypatch.setattr(
        TelegramNotifier,
        "send",
        lambda self, text, **kwargs: sent.append((text, kwargs.get("chat_id"))),
    )
    client = TestClient(create_app())

    response = client.post(
        "/telegram/webhook",
        json={"message": {"chat": {"id": 123}, "text": "/bingx_test_position SHORT 20000 20100 19900"}},
    )

    assert response.json() == {"status": "dry_run", "detail": "prepared bingx test order"}
    assert seen[0][0] == "bingx"
    assert seen[0][1] is True
    assert seen[0][2].symbol == "NASDAQ100-USDT"
    assert seen[0][2].direction == "SHORT"
    assert seen[0][2].price == 20000
    assert seen[0][2].sl == 20100
    assert seen[0][2].tp == 19900
    assert any("Dry Run" in text for text, _chat_id in sent)


def test_test_position_command_reports_usage_errors(monkeypatch):
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: settings()))
    sent = []
    monkeypatch.setattr(
        TelegramNotifier,
        "send",
        lambda self, text, **kwargs: sent.append((text, kwargs.get("chat_id"))),
    )
    client = TestClient(create_app())

    response = client.post(
        "/telegram/webhook",
        json={"message": {"chat": {"id": 123}, "text": "/vanta_test_position LONG 20000"}},
    )

    assert response.json()["status"] == "error"
    assert any(
        "Usage: /vanta_test_position or /bingx_test_position LONG|SHORT ENTRY SL TP" in text
        for text, _chat_id in sent
    )


def test_startup_registers_railway_telegram_webhook(monkeypatch):
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: settings()))
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "bot-production.up.railway.app")
    registered = []
    monkeypatch.setattr(
        TelegramNotifier,
        "set_webhook",
        lambda self, url: registered.append(url) or True,
    )
    monkeypatch.setattr(TelegramNotifier, "send", lambda self, text, **kwargs: None)
    monkeypatch.setattr(TelegramNotifier, "set_commands", lambda self: True)

    with TestClient(create_app()):
        pass

    assert registered == [
        "https://bot-production.up.railway.app/telegram/webhook"
    ]
