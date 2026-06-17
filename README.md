# NASDAQ Pre-NYSE IB Raid/Extension Bot

Starter project for a two-part NASDAQ trading workflow:

1. TradingView Pine Script calculates the Initial Balance from 08:00-09:30 New York time by default and currently backtests extension/raid entries.
2. Python FastAPI webhook receives TradingView JSON alerts, sends Telegram notifications, and opens cTrader positions through cTrader Open API.

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
src/market_profile_bot/                              Python webhook, Telegram notifier, and cTrader executor
tests/                                               Unit tests for alert/risk logic
```

## TradingView Setup

1. Open `tradingview/nasdaq_pre_nyse_ib_raid_extension.pine` in TradingView Pine Editor.
2. Add it to a 5m NASDAQ chart.
3. Set the Pine input `Webhook secret` to the same value as `WEBHOOK_SECRET` in your Python `.env`.
4. Create an alert with condition: **Any alert() function call**.
5. Set webhook URL to your bot endpoint, for example:

```text
https://your-domain.example/webhook/tradingview
```

The script sends JSON payloads, so do not replace the alert message with manual text.

## Python Setup

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```

Create a local `.env` file:

```bash
WEBHOOK_SECRET=change-me

CTRADER_HOST_TYPE=demo
CTRADER_CLIENT_ID=
CTRADER_CLIENT_SECRET=
CTRADER_REDIRECT_URI=http://127.0.0.1:8000/ctrader/callback
CTRADER_ACCESS_TOKEN=
CTRADER_REFRESH_TOKEN=
CTRADER_ACCOUNT_ID=
CTRADER_SYMBOL_ID=
CTRADER_SYMBOL_NAME=NAS100
CTRADER_VOLUME=1000
CTRADER_SLIPPAGE_POINTS=20

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
uvicorn market_profile_bot.app:create_app --factory --host 0.0.0.0 --port 8000
```

Use `DRY_RUN=true` until you have verified payloads, symbol name, cTrader volume, and broker execution.

## cTrader Setup

1. Create an application in the cTrader Open API portal.
2. Add your redirect URI. For local setup use:

```text
http://127.0.0.1:8000/ctrader/callback
```

3. Fill `.env`:

```env
CTRADER_CLIENT_ID=
CTRADER_CLIENT_SECRET=
CTRADER_REDIRECT_URI=http://127.0.0.1:8000/ctrader/callback
```

4. Start the bot.
5. Open:

```text
http://127.0.0.1:8000/ctrader/auth-url
```

6. Open the returned `auth_url`, approve trading access, and let cTrader redirect to `/ctrader/callback`.
7. Copy `CTRADER_ACCESS_TOKEN` and `CTRADER_REFRESH_TOKEN` from the response into `.env`.
8. Restart the bot, then open:

```text
http://127.0.0.1:8000/ctrader/accounts
```

9. Copy `ctidTraderAccountId` into `CTRADER_ACCOUNT_ID`, restart the bot, then search symbols:

```text
http://127.0.0.1:8000/ctrader/symbols?q=NAS
```

10. Copy the correct `symbolId` into `CTRADER_SYMBOL_ID` and fill the volume:

```env
CTRADER_ACCOUNT_ID=
CTRADER_SYMBOL_ID=
CTRADER_VOLUME=
```

Use a demo account first. `CTRADER_VOLUME` uses cTrader Open API volume units, not the position-size labels shown in every trading platform UI.

## Mac/Linux VPS Launch

1. Install Python 3.12 and Git.
2. Clone or copy this project to the VPS.
3. Open a terminal in the project directory.
4. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

5. Install dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```

6. Fill `.env` with VPS/demo settings. Start with:

```env
DRY_RUN=true
AUTO_TRADE=false
```

7. Run the bot:

```bash
python -m uvicorn market_profile_bot.app:create_app --factory --host 0.0.0.0 --port 8000
```

8. Test locally on the VPS:

```bash
curl http://127.0.0.1:8000/health
```

9. Expose the webhook with your VPS public IP/domain and firewall rule for port `8000`, or put Nginx/Caddy in front of it with HTTPS.

TradingView webhook URL:

```text
http://YOUR_VPS_IP:8000/webhook/tradingview
```

Use HTTPS before live trading if possible.

## Docker Setup

The Docker image runs the FastAPI webhook service, Telegram notifications, and cTrader Open API execution.

Build and run:

```bash
docker compose up --build
```

Check health:

```bash
curl http://127.0.0.1:8000/health
```

Stop:

```bash
docker compose down
```

`docker-compose.yml` reads `.env`, so `DRY_RUN` and `AUTO_TRADE` are controlled there. Keep `DRY_RUN=true` until the webhook, Telegram, cTrader symbol, and demo execution are verified.

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
- cTrader execution requires `CTRADER_ACCESS_TOKEN`, `CTRADER_ACCOUNT_ID`, `CTRADER_SYMBOL_ID`, and `CTRADER_VOLUME`.
- Telegram notifications are disabled unless `TELEGRAM_ENABLED=true`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_CHAT_ID` are configured.
