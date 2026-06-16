# NASDAQ Pre-NYSE IB Raid/Extension Bot

Starter project for a two-part NASDAQ trading workflow:

1. TradingView Pine Script calculates the Initial Balance from 08:00-09:30 New York time by default and currently backtests extension/raid entries.
2. Python FastAPI webhook receives TradingView JSON alerts and opens MT5 positions.

Current strategy defaults:

- Instrument: NASDAQ / NAS100 / USTEC, depending on broker symbol.
- Working timeframe: 5m.
- IB: 08:00-09:30 America/New_York.
- Trade session: 09:30-16:00 America/New_York.
- One position per day.
- Risk per position: 1% of account equity.
- Reward:risk: 1:1.
- 15m EMA filter:
  - EMA125 above EMA200: only long entries are allowed.
  - EMA125 below EMA200: only short entries are allowed.
  - Blocked opposite-direction setups are discarded, so the strategy keeps looking for an allowed direction until the day ends.
- IB extension: one IB border breakout/raid, confirmed fractal beyond that border, then close beyond the fractal. SL is the opposite IB border.
- IB raid: one IB border raid, with same-side re-raids allowed before the opposite border. After return to IB, the opposite border raid can enter by same-candle close beyond that border, next-candle continuation when no fractal forms, or BoS through the opposite-side raid fractal.

## Project Layout

```text
tradingview/nasdaq_pre_nyse_ib_raid_extension.pine  Pine strategy and alerts
src/market_profile_bot/                              Python webhook, Telegram notifier, and MT5 executor
tests/                                               Unit tests for alert/risk logic
```

## TradingView Setup

1. Open `tradingview/nasdaq_pre_nyse_ib_raid_extension.pine` in TradingView Pine Editor.
2. Add it to a 5m NASDAQ chart.
3. Create an alert with condition: **Any alert() function call**.
4. Set webhook URL to your bot endpoint, for example:

```text
https://your-domain.example/webhook/tradingview
```

5. Set the Pine input `Webhook secret` to the same value as `WEBHOOK_SECRET` in your Python `.env`.

The script sends JSON payloads, so do not replace the alert message with manual text.

## Python Setup

Install dependencies:

```bash
.venv/bin/python -m pip install -r requirements.txt
```

Create a local `.env` file:

```bash
WEBHOOK_SECRET=change-me
MT5_LOGIN=12345678
MT5_PASSWORD=your-password
MT5_SERVER=YourBroker-Server
MT5_SYMBOL=NAS100
MT5_DEVIATION=20
MT5_MAGIC=404011
DRY_RUN=true
AUTO_TRADE=false
MARKET_TIMEZONE=America/New_York
ENTRY_CUTOFF=16:00
TELEGRAM_ENABLED=false
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

Run locally:

```bash
.venv/bin/uvicorn market_profile_bot.app:create_app --factory --host 0.0.0.0 --port 8000
```

Use `DRY_RUN=true` until you have verified payloads, symbol name, lot size, and broker execution.

## Webhook Payloads

Example `RAID` alert:

```json
{
  "secret": "change-me",
  "id": "NAS100-2026-06-10T10:05:00-04:00-RAID-SHORT",
  "type": "RAID",
  "symbol": "NAS100",
  "time": "2026-06-10T10:05:00-04:00",
  "direction": "SHORT",
  "price": 18425.5,
  "ib_high": 18510.0,
  "ib_low": 18390.0,
  "ib_mid": 18450.0,
  "sl": 18510.0,
  "tp": 18341.0,
  "risk_percent": 1.0,
  "rr": 1.0,
  "source": "tradingview"
}
```

`IB_READY` does not open trades. `RAID` and `EXTENSION` can open trades when `AUTO_TRADE=true`.

## Important Defaults

- The Python bot defaults to `DRY_RUN=true` and `AUTO_TRADE=false`.
- Duplicate alert IDs are ignored during the process lifetime.
- Only one auto-traded signal is accepted per market day.
- The server-side entry cutoff defaults to `16:00` in `America/New_York`.
- Trade alerts must include `sl` and `tp`.
- Live MT5 volume is calculated from `risk_percent`, account equity, stop distance, and broker tick value.
- Telegram notifications are disabled unless `TELEGRAM_ENABLED=true`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_CHAT_ID` are configured.
