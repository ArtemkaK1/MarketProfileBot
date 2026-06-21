# NASDAQ Pre-NYSE IB Raid/Extension Bot

Starter project for a two-part NASDAQ trading workflow:

1. TradingView Pine Script calculates the Initial Balance from 08:00-09:30 New York time by default and currently backtests extension/raid entries.
2. Python FastAPI webhook receives TradingView JSON alerts, sends Telegram notifications, and opens BingX positions.

Current strategy defaults:

- Instrument: NASDAQ / NAS100 / USTEC, depending on broker symbol.
- Working timeframe: 5m.
- IB: 08:00-09:30 America/New_York.
- Trade session: 09:30-16:00 America/New_York.
- One position per day.
- Backtest market orders are processed on the confirmed signal-bar close, matching the price used for SL, TP, sizing, and webhook alerts.
- Long entries are enabled by default. Short entries remain available but default to disabled after producing negative expectancy over the full-history backtest.
- Risk per position: 1% of account equity.
- Reward:risk: 1:1.
- 15m EMA filter:
  - EMA125 above EMA200: only long entries are allowed.
  - EMA125 below EMA200: only short entries are allowed.
  - Blocked opposite-direction setups are discarded, so the strategy keeps looking for an allowed direction until the day ends.
- IB extension: one IB border breakout/raid, confirmed fractal beyond that border, then close beyond the fractal. SL is the opposite IB border.
- IB raid: one IB border raid establishes the first-side manipulation and the opposite trade direction. A raid returns only when a candle closes back inside the IB. Re-raids can repeat on either side before entry. A first-side re-raid replaces the SL reference with the latest manipulation extreme and restarts the opposite-side setup; an opposite-side re-raid restarts its same-candle, next-candle, and fractal confirmation sequence. Raid SL defaults to one tick beyond the latest manipulation. Entry occurs by same-candle close beyond the opposite border, next-candle continuation beyond that raid's extreme when no fractal forms, or BoS through the current opposite-side raid fractal. Bars crossing both IB borders are marked ambiguous and do not establish a raid order because 5m OHLC cannot reveal which side crossed first.

## MetaTrader 5

An MT5 Expert Advisor port is available at `mql5/NasdaqPreNyseIBRaidExtension.mq5`. Installation, broker-time configuration, backtesting, and demo/live validation instructions are in `mql5/MT5_SETUP.md`.

## Project Layout

```text
tradingview/nasdaq_pre_nyse_ib_raid_extension.pine  Pine strategy and alerts
src/market_profile_bot/                              Python webhook, Telegram notifier, and BingX executor
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

BINGX_API_KEY=
BINGX_SECRET_KEY=
BINGX_SYMBOL=NASDAQ100-USDT
BINGX_INITIAL_CAPITAL=100
BINGX_RISK_PERCENT=5.0
BINGX_MIN_USDT_STEP=0.01

DRY_RUN=true
AUTO_TRADE=false
MARKET_TIMEZONE=America/New_York
ENTRY_CUTOFF=16:00
TELEGRAM_ENABLED=false
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TELEGRAM_WEBHOOK_URL=
```

### Telegram commands

The bot supports `/state`, which reports the current BingX USDT perpetual-futures balance,
available margin, margin mode, and long/short leverage for `BINGX_SYMBOL`.

The bot registers its Telegram webhook automatically at startup. On Railway it uses
`RAILWAY_PUBLIC_DOMAIN`. Outside Railway, set the public base URL explicitly:

```env
TELEGRAM_WEBHOOK_URL=https://YOUR-DOMAIN
```

Only commands from `TELEGRAM_CHAT_ID` are accepted. The BingX API key needs permission to
read the futures account; trading permission is still required for live order execution.

Run locally:

```bash
uvicorn market_profile_bot.app:create_app --factory --host 0.0.0.0 --port 8000
```

Use `DRY_RUN=true` until you have verified payloads, symbol name, calculated USDT size, and broker execution.

## BingX Setup

Create a BingX API key with trading permission and fill:

```env
BINGX_API_KEY=
BINGX_SECRET_KEY=
BINGX_SYMBOL=NASDAQ100-USDT
BINGX_INITIAL_CAPITAL=100
BINGX_RISK_PERCENT=5.0
BINGX_MIN_USDT_STEP=0.01
```

Confirm the exact TradFi NASDAQ100 API symbol in BingX. If the real symbol differs, update `BINGX_SYMBOL`.

The bot assumes BingX order size is USDT notional. It calculates size from the TradingView alert entry price and SL:

```text
risk_amount = BINGX_INITIAL_CAPITAL * BINGX_RISK_PERCENT / 100
raw_usdt_size = risk_amount * entry_price / abs(entry_price - stop_loss)
usdt_size = raw_usdt_size rounded up to BINGX_MIN_USDT_STEP
```

Rounding is upward, so actual risk is as close as possible to the target but not below it. Example: with `100` capital, `5%` risk, `20000` entry, and `19800` SL:

```text
risk_amount = 5
stop_distance = 200
raw_usdt_size = 5 * 20000 / 200 = 500
usdt_size = 500
```

The BingX REST base URL, order endpoint, request size field, receive window, and SL/TP request shape are code defaults because they are implementation details, not deployment settings.

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

The Docker image runs the FastAPI webhook service, Telegram notifications, and BingX execution.

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

`docker-compose.yml` reads `.env`, so `DRY_RUN` and `AUTO_TRADE` are controlled there. Keep `DRY_RUN=true` until the webhook, Telegram, BingX symbol, and demo execution are verified.

## Railway Deploy

1. Push this repository to GitHub.
2. In Railway, create a new project and select **Deploy from GitHub repo**.
3. Select this repository. Railway automatically detects and builds the root `Dockerfile`.
4. Add these variables to the service's **Variables** tab:

```env
WEBHOOK_SECRET=
BINGX_API_KEY=
BINGX_SECRET_KEY=
BINGX_SYMBOL=NASDAQ100-USDT
BINGX_INITIAL_CAPITAL=100
BINGX_RISK_PERCENT=5.0
BINGX_MIN_USDT_STEP=0.01
DRY_RUN=true
AUTO_TRADE=false
MARKET_TIMEZONE=America/New_York
ENTRY_CUTOFF=16:00
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

5. Under **Settings → Networking**, generate a public domain.
6. Under the service settings, set the healthcheck path to `/health`.
7. Deploy, then check:

```text
https://YOUR-SERVICE.up.railway.app/health
```

TradingView webhook URL:

```text
https://YOUR-SERVICE.up.railway.app/webhook/tradingview
```

Telegram command delivery is configured automatically from Railway's public domain when
the service starts. The deployment logs should contain `Telegram webhook registered`.

Keep `DRY_RUN=true` and `AUTO_TRADE=false` for the first alert test. When Telegram receives the signal and `/health` is stable, switch `AUTO_TRADE=true` while keeping `DRY_RUN=true`. Only switch `DRY_RUN=false` after a small live test is acceptable.

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
- BingX execution requires `BINGX_API_KEY`, `BINGX_SECRET_KEY`, `BINGX_SYMBOL`, `BINGX_INITIAL_CAPITAL`, `BINGX_RISK_PERCENT`, and `BINGX_MIN_USDT_STEP`.
- Telegram notifications are disabled unless `TELEGRAM_ENABLED=true`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_CHAT_ID` are configured.
