from datetime import datetime

from market_profile_bot.models import TradingViewAlert
from market_profile_bot.telegram import TelegramNotifier, format_signal_message


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

    assert "TradingView signal: EXTENSION LONG" in message
    assert "Symbol: NAS100" in message
    assert "SL: 18850.0" in message
    assert "TP: 19150.0" in message
    assert "Risk: 1.0%" in message


def test_format_ib_ready_message_contains_ib_levels():
    alert = TradingViewAlert.model_validate(
        payload(type="IB_READY", direction="NONE", sl=None, tp=None)
    )

    message = format_signal_message(alert)

    assert "TradingView signal: IB_READY" in message
    assert "IB High: 18950.0" in message
    assert "IB Low: 18850.0" in message
    assert "IB 0.5: 18900.0" in message


def test_bot_started_message_contains_runtime_flags(monkeypatch):
    sent = []
    notifier = TelegramNotifier(bot_token="token", chat_id="chat", enabled=True)
    monkeypatch.setattr(TelegramNotifier, "send", lambda _self, text: sent.append(text))

    notifier.bot_started(backend="bingx", dry_run=True, auto_trade=False)

    assert sent == ["Bot is active\nBackend: bingx\nDRY_RUN: True\nAUTO_TRADE: False"]
