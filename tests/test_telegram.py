from datetime import datetime
from decimal import Decimal

from market_profile_bot.models import TradingViewAlert
from market_profile_bot.telegram import (
    TelegramNotifier,
    format_account_state_message,
    format_signal_message,
)
from market_profile_bot.trading import AccountState
from market_profile_bot import telegram


def payload(**overrides):
    data = {
        "secret": "secret",
        "id": "id-1",
        "type": "EXTENSION",
        "symbol": "NAS100",
        "time": datetime.fromisoformat("2026-06-10T10:00:00-04:00"),
        "direction": "LONG",
        "price": 19000.0,
        "ib_high": 18950.0,
        "ib_low": 18850.0,
        "ib_mid": 18900.0,
        "sl": 18850.0,
        "tp": 19150.0,
        "risk_percent": 1.0,
        "rr": 1.0,
        "source": "tradingview",
    }
    data.update(overrides)
    return data


def test_telegram_notifier_requires_enabled_token_and_chat_id():
    assert not TelegramNotifier(bot_token="token", chat_id="chat", enabled=False).configured
    assert not TelegramNotifier(bot_token=None, chat_id="chat", enabled=True).configured
    assert not TelegramNotifier(bot_token="token", chat_id=None, enabled=True).configured
    assert TelegramNotifier(bot_token="token", chat_id="chat", enabled=True).configured


def test_format_trade_signal_message_contains_order_context():
    alert = TradingViewAlert.model_validate(payload())

    message = format_signal_message(alert)

    assert "Extension signal · LONG" in message
    assert "Symbol: NAS100" in message
    assert "Stop loss: 18850.0" in message
    assert "Take profit: 19150.0" in message
    assert "Bot risk: 1%" in message


def test_format_trade_signal_uses_configured_bot_risk():
    alert = TradingViewAlert.model_validate(payload(risk_percent=5.0))

    message = format_signal_message(alert, risk_percent=10.0)

    assert "Bot risk: 10%" in message
    assert "Bot risk: 5%" not in message


def test_format_trade_signal_shows_adjusted_long_levels():
    alert = TradingViewAlert.model_validate(payload())

    message = format_signal_message(alert, sl_tp_offset_points=2.5)

    assert "Stop loss: 18847.5" in message
    assert "Take profit: 19152.5" in message


def test_format_ib_ready_message_contains_ib_levels():
    alert = TradingViewAlert.model_validate(
        payload(type="IB_READY", direction="NONE", sl=None, tp=None)
    )

    message = format_signal_message(alert)

    assert "Initial balance is ready" in message
    assert "High: 18950.0" in message
    assert "Low: 18850.0" in message
    assert "Midpoint: 18900.0" in message


def test_bot_started_message_contains_runtime_flags(monkeypatch):
    sent = []
    notifier = TelegramNotifier(bot_token="token", chat_id="chat", enabled=True)
    monkeypatch.setattr(
        TelegramNotifier, "send", lambda _self, text, **kwargs: sent.append(text)
    )

    notifier.bot_started(backend="vanta_trading", dry_run=True, auto_trade=False)

    assert "🟢 Bot started" in sent[0]
    assert "Execution: Simulation" in sent[0]
    assert "Auto-trading: Off" in sent[0]
    assert "/vanta_state" in sent[0]
    assert "/vanta_test_position" in sent[0]
    assert "/bingx_state" in sent[0]
    assert "/bingx_test_position" in sent[0]


def test_format_account_state_message_shows_buying_power_and_leverage():
    state = AccountState(
        platform="VantaTrading",
        symbol="XYZ100/USDC",
        balance=Decimal("123.4500"),
        buying_power=Decimal("185.175"),
        available_margin=Decimal("100.00"),
        leverage=Decimal("1.5"),
        currency="USDC",
    )

    message = format_account_state_message(state)

    assert "VantaTrading" in message
    assert "Balance: 123.45 USDC" in message
    assert "Available margin: 100 USDC" in message
    assert "Buying power: 185.175 USDC" in message
    assert "Leverage: 1.5x" in message


def test_set_webhook_registers_allowed_message_updates(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'{"ok": true, "result": true}'

    captured = []

    def fake_urlopen(req, timeout):
        captured.append((req, timeout))
        return Response()

    monkeypatch.setattr(telegram.request, "urlopen", fake_urlopen)
    notifier = TelegramNotifier(bot_token="token", chat_id="123", enabled=True)

    assert notifier.set_webhook("https://example.com/telegram/webhook")
    assert captured[0][0].full_url.endswith("/bottoken/setWebhook")
    assert b"https%3A%2F%2Fexample.com%2Ftelegram%2Fwebhook" in captured[0][0].data
    assert b"allowed_updates" in captured[0][0].data


def test_set_commands_registers_platform_specific_commands(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'{"ok": true, "result": true}'

    captured = []

    def fake_urlopen(req, timeout):
        captured.append((req, timeout))
        return Response()

    monkeypatch.setattr(telegram.request, "urlopen", fake_urlopen)
    notifier = TelegramNotifier(bot_token="token", chat_id="123", enabled=True)

    assert notifier.set_commands()
    assert captured[0][0].full_url.endswith("/bottoken/setMyCommands")
    body = captured[0][0].data.decode()
    assert "vanta_state" in body
    assert "vanta_test_position" in body
    assert "bingx_state" in body
    assert "bingx_test_position" in body
