from datetime import time
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from market_profile_bot.app import create_app
from market_profile_bot.bingx_executor import BingXAccountState, BingXExecutor
from market_profile_bot.config import Settings
from market_profile_bot.telegram import TelegramNotifier


def settings() -> Settings:
    return Settings(
        webhook_secret="secret",
        bingx_api_key="key",
        bingx_secret_key="secret",
        bingx_symbol="NASDAQ100-USDT",
        bingx_risk_percent=5,
        bingx_min_usdt_step=0.01,
        bingx_max_notional_usdt=1000,
        dry_run=True,
        auto_trade=False,
        timezone=ZoneInfo("America/New_York"),
        entry_cutoff=time(16, 0),
        telegram_bot_token="token",
        telegram_chat_id="123",
        telegram_enabled=True,
    )


def test_state_command_replies_only_to_configured_chat(monkeypatch):
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: settings()))
    monkeypatch.setattr(
        BingXExecutor,
        "current_state",
        lambda self: BingXAccountState(
            symbol="NASDAQ100-USDT",
            balance=Decimal("123.45"),
            available_margin=Decimal("100"),
            margin_type="CROSSED",
            long_leverage=Decimal("10"),
            short_leverage=Decimal("10"),
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
        json={"message": {"chat": {"id": 123}, "text": "/state"}},
    )
    denied = client.post(
        "/telegram/webhook",
        json={"message": {"chat": {"id": 999}, "text": "/state"}},
    )

    assert allowed.json() == {"status": "ok"}
    assert denied.json() == {"status": "ignored"}
    assert len(sent) == 1
    assert "Balance: 123.45 USDT" in sent[0][0]
    assert sent[0][1] == "123"


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

    with TestClient(create_app()):
        pass

    assert registered == [
        "https://bot-production.up.railway.app/telegram/webhook"
    ]
