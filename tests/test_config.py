from market_profile_bot.config import Settings


def test_telegram_webhook_url_uses_railway_public_domain(monkeypatch):
    monkeypatch.delenv("TELEGRAM_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "bot.up.railway.app")

    assert Settings.from_env().telegram_webhook_url == (
        "https://bot.up.railway.app/telegram/webhook"
    )


def test_explicit_telegram_webhook_url_takes_precedence(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_URL", "https://bot.example.com/")
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "bot.up.railway.app")

    assert Settings.from_env().telegram_webhook_url == (
        "https://bot.example.com/telegram/webhook"
    )
