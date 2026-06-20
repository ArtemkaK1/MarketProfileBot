# Complete beginner guide: running the strategy in MetaTrader 5

This guide assumes you have never used MQL5 or an Expert Advisor.

## 1. What the files and terms mean

- **MetaTrader 5 (MT5)** is the trading terminal where charts, accounts, orders, and backtests run.
- **MQL5** is the programming language used by MT5.
- An **Expert Advisor (EA)** is an automated strategy program.
- A `.mq5` file is editable source code.
- MetaEditor compiles it into an `.ex5` file that MT5 can run.
- This project's EA source file is `NasdaqPreNyseIBRaidExtension.mq5`.

You do not need to edit the code to use the EA. You install the source, compile it once, and configure its inputs in MT5.

## 2. Safety model used by this EA

There are three separate trading switches:

1. `InpAllowLiveTrading`, an EA input, defaults to `false`.
2. **Allow algorithmic trading** in the EA's Common tab.
3. MT5's global **Algo Trading** button.

An order can be sent only when all three allow trading. Keep `InpAllowLiveTrading=false` for installation and signal checks. Use a demo account before considering live trading.

This EA can open and manage real orders. Backtest results do not prove future profitability.

## 3. Install MetaTrader 5 and obtain a demo account

1. Download MT5 from your broker. A broker-supplied terminal normally has the broker's servers and symbols preconfigured.
2. Install and open MT5.
3. Sign in to a **demo** trading account. If you do not have one, use **File → Open an Account** and follow the broker's demo-account flow.
4. Confirm that prices are moving in **Market Watch**. If Market Watch is hidden, open it with **View → Market Watch** or `Ctrl+M`.

The strategy needs the broker's NASDAQ CFD. Common names include `NAS100`, `US100`, `USTEC`, `NDX`, and names with suffixes such as `NAS100.cash`. Symbol names and contract specifications differ by broker.

To find the symbol:

1. In Market Watch, right-click and select **Symbols**.
2. Search for `NAS`, `US100`, `USTEC`, or `NDX`.
3. Select the broker's cash/index CFD rather than a similarly named unrelated instrument.
4. Click **Show Symbol**, then close the dialog.
5. Right-click the symbol in Market Watch and open **Specification**. Note its trading hours, minimum volume, volume step, tick size, and tick value.

If no NASDAQ CFD is available, this EA cannot trade the intended market through that broker.

## 4. Copy the EA into MT5

Do not guess where MT5 stores its files. Let MT5 open the correct data directory.

1. In MT5, select **File → Open Data Folder**.
2. Open `MQL5`.
3. Open `Experts`.
4. Create a folder named `MarketProfileBot`.
5. Copy `NasdaqPreNyseIBRaidExtension.mq5` from this project into that folder.

The resulting structure should be:

```text
MT5 data folder/
└── MQL5/
    └── Experts/
        └── MarketProfileBot/
            └── NasdaqPreNyseIBRaidExtension.mq5
```

On macOS, MT5 may use a compatibility layer and show an unfamiliar directory tree. **File → Open Data Folder** is still the correct method.

## 5. Compile the EA

Compilation converts the source code into the executable file MT5 uses.

1. In MT5, press `F4` to open MetaEditor. You can also right-click **Expert Advisors** in Navigator and choose **Create in MetaEditor**, then open the existing file.
2. In MetaEditor's left Navigator, expand **Experts → MarketProfileBot**.
3. Double-click `NasdaqPreNyseIBRaidExtension.mq5`.
4. Press `F7` or click **Compile**.
5. Check the Toolbox/Errors panel at the bottom.

The required result is:

```text
0 errors
```

Warnings should also be reviewed, but errors prevent installation. Successful compilation creates `NasdaqPreNyseIBRaidExtension.ex5` beside the source file.

If the file is absent from MetaEditor:

- verify that it was copied into the data folder opened by this exact MT5 installation;
- verify that it is under `MQL5/Experts`, not `MQL5/Indicators` or the project directory;
- restart MetaEditor or refresh its Navigator.

If compilation reports errors, copy the complete error list, including line numbers. Do not enable trading until compilation succeeds.

## 6. Make the EA appear in MT5

1. Return to MT5.
2. Open Navigator with **View → Navigator** or `Ctrl+N`.
3. Expand **Expert Advisors**.
4. Right-click **Expert Advisors** and choose **Refresh**.
5. Find **MarketProfileBot → NasdaqPreNyseIBRaidExtension**.

If it does not appear, confirm that the `.ex5` file was generated and restart MT5.

## 7. Determine the broker server UTC offset

This is the most important configuration step. The strategy defines sessions in New York time, while MT5 candle timestamps use broker server time.

`InpBrokerUtcOffsetHours` means:

```text
broker server time minus UTC time
```

To determine it:

1. Look at the current broker time shown with live quotes in Market Watch.
2. Compare it with the current UTC time from a reliable UTC clock.
3. Subtract UTC from broker time.

Examples:

- Broker server shows 12:00 and UTC is 10:00: enter `2`.
- Broker server shows 13:00 and UTC is 10:00: enter `3`.
- Broker server shows 08:00 and UTC is 10:00: enter `-2`.

Do not enter your computer timezone and do not enter the New York offset. The EA converts from broker time to UTC and then to New York time. New York daylight-saving transitions are handled automatically.

Many brokers change server offset between UTC+2 and UTC+3. The EA accepts one offset for a run, so:

- update the input when the broker changes its server clock;
- for historical tests spanning an offset change, test each offset period separately;
- pay special attention to March and November, when US and broker clock-change dates may differ.

An incorrect offset moves the IB and trading sessions and invalidates the test.

## 8. Open the correct chart

1. In Market Watch, right-click the NASDAQ symbol and select **Chart Window**.
2. Set the timeframe to **M5** using the toolbar or **Charts → Timeframes → 5 Minutes**.
3. Allow MT5 to download history. Scroll backward or press `Home` several times if needed.

The EA warns in the Experts log if attached to a timeframe other than M5.

## 9. First attachment: signal-only mode

1. Drag the EA from Navigator onto the M5 NASDAQ chart.
2. Open the **Common** tab. For this first check, leave algorithmic trading disabled.
3. Open the **Inputs** tab.
4. Set `InpBrokerUtcOffsetHours` correctly.
5. Confirm `InpAllowLiveTrading=false`.
6. Leave the remaining strategy defaults unchanged.
7. Click **OK**.

The EA name should appear on the chart. Open the Toolbox with `Ctrl+T`, then inspect:

- **Experts** for EA status, IB values, signals, and order errors;
- **Journal** for terminal-level connection and permission messages.

In signal-only mode, a valid signal produces a message beginning with:

```text
SIGNAL ONLY:
```

No order is sent. The signal is still marked as the day's one allowed trade, matching the strategy rule.

Attach the EA before 08:00 New York when possible. If attached later, it replays up to 600 M5 bars to reconstruct state but does not place an old order.

## 10. Input reference

### Sessions and time

| Input | Default | Meaning |
|---|---:|---|
| `InpBrokerUtcOffsetHours` | `2` | Broker server offset from UTC. You must verify this. |
| `InpIBStartHour` / `Minute` | `08:00` | Initial Balance start in New York time. |
| `InpIBEndHour` / `Minute` | `09:30` | Initial Balance end and trade-session start in New York time. |
| `InpTradeEndHour` / `Minute` | `16:00` | Last session boundary for new signals in New York time. |

### Strategy logic

| Input | Default | Meaning |
|---|---:|---|
| `InpFractalLeft` | `1` | Bars required to the left of a pivot. |
| `InpFractalRight` | `1` | Bars required to the right; this delays confirmation. |
| `InpBreakoutNeedsClose` | `false` | `false` permits a wick beyond IB; `true` requires the candle close beyond it. |
| `InpEnableExtensionLong` | `true` | Allows long extension trades. |
| `InpEnableExtensionShort` | `false` | Allows short extension trades. |
| `InpEnableRaidLong` | `true` | Allows long raid trades. |
| `InpEnableRaidShort` | `false` | Allows short raid trades. |
| `InpRaidStopBufferTicks` | `1` | Stop buffer beyond the latest raid extreme. |
| `InpEmaTimeframe` | `M15` | Timeframe for the trend filter. |
| `InpEmaFastLength` | `125` | Fast EMA length. |
| `InpEmaSlowLength` | `200` | Slow EMA length. |

### Risk and execution

| Input | Default | Meaning |
|---|---:|---|
| `InpRiskCapital` | `100000` | Fixed capital base used to calculate cash risk. It is not read from account equity. |
| `InpRiskPercent` | `1` | Percentage of `InpRiskCapital` risked at the stop. |
| `InpRewardRisk` | `1` | Take-profit multiple; `1` means 1R. |
| `InpMagicNumber` | `25093001` | Identifier attached to this EA's orders. Use a different value for separate instances. |
| `InpMaxDeviationPoints` | `30` | Maximum execution deviation in broker points. Points are not necessarily index points. |
| `InpAllowLiveTrading` | `false` | EA-level order permission. Keep false until demo validation. |

With the defaults, cash risk is calculated as:

```text
100000 × 1% = 1000 account-currency units
```

If your intended risk capital is 10,000, set `InpRiskCapital=10000`; at 1%, intended risk becomes 100. Actual loss can differ because of gaps, slippage, commission, spread, rejected stops, or abnormal execution.

The EA rounds volume down to the broker's volume step. It rejects a calculated volume below the broker minimum rather than increasing risk by rounding up.

## 11. Run the first backtest

1. Open **View → Strategy Tester** or press `Ctrl+R`.
2. Select `NasdaqPreNyseIBRaidExtension` as the Expert Advisor.
3. Select the exact NASDAQ symbol used on the chart.
4. Select **M5** as the period.
5. Select **Every tick based on real ticks** as the model when the broker supplies real tick history.
6. Select a date range. Include sufficient earlier data for the M15 EMA200. Several weeks of warm-up is a practical minimum.
7. Set a realistic initial deposit and leverage for the account being modeled.
8. Open **Inputs** and set the historically correct broker UTC offset.
9. Set `InpAllowLiveTrading=true`. In Strategy Tester, this allows simulated orders; it does not trade the live account.
10. Leave optimization disabled for the first run.
11. Optionally enable **Visual mode** to watch candles and trades.
12. Click **Start**.

Review these tabs after the run:

- **Results/Backtest**: each simulated deal and order;
- **Graph**: balance/equity path;
- **Report**: profit, drawdown, trade count, and quality metrics;
- **Journal**: initialization, IB values, rejected orders, missing history, and execution errors.

Do not judge the strategy from net profit alone. Check trade count, maximum drawdown, profit factor, average trade, consecutive losses, spread sensitivity, and whether individual signal dates agree with TradingView.

## 12. Why MT5 and TradingView can differ

Perfectly identical results are not expected unless both platforms use identical candles and execution assumptions.

Common causes:

- different broker price feeds and candle highs/lows;
- different NASDAQ CFD trading hours;
- missing or low-quality historical ticks;
- incorrect broker UTC offset;
- spread, commission, minimum stop distance, and slippage;
- volume and price-step rounding;
- TradingView modeling an order at the signal candle close;
- live MT5 learning that close only on the next candle's first tick.

The EA therefore evaluates the completed candle and sends a market order on the first tick of the new candle. It calculates volume and TP from the executable bid/ask price.

## 13. Validate against TradingView

Before demo automation, compare at least 10–20 historical setup days.

For each day record:

```text
Date
IB high
IB low
EMA direction
Setup type: RAID or EXTENSION
Direction
Signal candle time
Entry
Stop
Target
Outcome
```

If the IB differs, investigate timezone and feed/session data first. If the IB matches but the signal differs, compare fractal candles and wick/close breakout settings. If the signal matches but P/L differs, investigate execution price, spread, commission, tick value, and contract size.

Do not optimize parameters until basic signal parity is acceptable. Otherwise optimization can hide a timing or data error.

## 14. Demo trading procedure

After signal-only checks and backtesting:

1. Confirm the terminal is connected to a demo account.
2. Open the NASDAQ M5 chart.
3. Attach the EA and set the correct broker UTC offset.
4. Set a deliberately small `InpRiskCapital` and `InpRiskPercent`.
5. Set `InpAllowLiveTrading=true`.
6. In the EA's **Common** tab, enable algorithmic trading.
7. Turn on MT5's global **Algo Trading** button.
8. Keep MT5 running and connected through the full session.
9. Watch **Experts**, **Journal**, **Trade**, and **History**.

For the first executed demo order, verify immediately:

- direction and setup type;
- filled entry price;
- stop-loss and take-profit are present;
- volume is consistent with intended cash risk;
- the stop is beyond the intended reference level;
- only one signal/order is taken that New York day.

If no SL or TP is present, disable Algo Trading and close/manage the position according to your risk policy before debugging.

## 15. Keeping the EA running

An EA only processes ticks while its MT5 terminal is running, connected, and permitted to trade. For continuous operation:

- prevent the computer from sleeping;
- maintain a stable network connection;
- keep the correct account logged in;
- keep the chart and EA attached;
- check that broker trading hours include the strategy session;
- consider a Windows VPS near the broker after demo validation.

Restarting MT5 or reattaching the EA does not intentionally place a historical signal. The EA reconstructs the current day and waits for a new valid signal.

## 16. Common problems

### The EA is missing from Navigator

- Compile it in MetaEditor.
- Confirm the `.ex5` file exists under `MQL5/Experts/MarketProfileBot`.
- Refresh Navigator or restart MT5.

### It logs signals but opens no order

Check all three permissions: `InpAllowLiveTrading`, the EA Common-tab permission, and the global Algo Trading button. Also confirm this is a demo/live chart rather than a closed market.

### It produces no signals

- Confirm the chart is M5.
- Confirm the symbol has candles from 08:00–16:00 New York.
- Verify the broker UTC offset.
- Check whether EMA history is loaded.
- Remember that the default short strategies are disabled.
- Check the Experts log for IB-ready messages.

### `Invalid stops`

The broker requires a larger minimum distance or the market moved before submission. Inspect the symbol Specification and the order error in Experts. Do not remove stops as a workaround.

### `Invalid volume` or volume is zero

Check minimum volume, volume step, tick size, and tick value in symbol Specification. The configured risk may be too small for the broker's minimum lot.

### `Not enough money`

The requested volume requires more margin than available. Reduce risk capital/percentage or use suitable leverage on a demo account.

### IB is shifted by one or more hours

`InpBrokerUtcOffsetHours` is wrong for that date, or the broker changed server offset. Correct the offset and rerun the test.

### Backtest has no trades but signal-only logs exist

Set `InpAllowLiveTrading=true` in Strategy Tester inputs. That enables simulated tester orders.

### MT5 results differ around March or November

Split the test around server/US daylight-saving transitions and apply the correct broker offset to each segment.

## 17. Moving toward live trading

Do not switch directly from compilation to a funded account. Use this progression:

1. Compile with zero errors.
2. Signal-only observation.
3. Historical backtest with real ticks.
4. TradingView parity review.
5. Small demo forward test over multiple weeks.
6. Review logs, rejected orders, realized risk, and restart behavior.
7. Only then consider the smallest acceptable funded-account risk.

Before funded use, preserve the exact `.mq5`, `.ex5`, input preset, broker symbol, broker offset, and test report used for approval. Change one thing at a time and repeat validation after code or parameter changes.
