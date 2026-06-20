#property copyright "MarketProfileBot"
#property version   "1.00"
#property strict

#include <Trade/Trade.mqh>

// MT5 Expert Advisor port of tradingview/nasdaq_pre_nyse_ib_raid_extension.pine.
// Designed for a 5-minute NASDAQ CFD chart. Signals are evaluated once a bar closes.

input group "Sessions and time"
input int      InpBrokerUtcOffsetHours = 2;       // Broker server offset from UTC (tester-safe)
input int      InpIBStartHour = 8;
input int      InpIBStartMinute = 0;
input int      InpIBEndHour = 9;
input int      InpIBEndMinute = 30;
input int      InpTradeEndHour = 16;
input int      InpTradeEndMinute = 0;

input group "Strategy"
input int      InpFractalLeft = 1;
input int      InpFractalRight = 1;
input bool     InpBreakoutNeedsClose = false;
input bool     InpEnableExtensionLong = true;
input bool     InpEnableExtensionShort = false;
input bool     InpEnableRaidLong = true;
input bool     InpEnableRaidShort = false;
input int      InpRaidStopBufferTicks = 1;
input ENUM_TIMEFRAMES InpEmaTimeframe = PERIOD_M15;
input int      InpEmaFastLength = 125;
input int      InpEmaSlowLength = 200;

input group "Risk and execution"
input double   InpRiskCapital = 100000.0;
input double   InpRiskPercent = 1.0;
input double   InpRewardRisk = 1.0;
input ulong    InpMagicNumber = 25093001;
input int      InpMaxDeviationPoints = 30;
input bool     InpAllowLiveTrading = false;

CTrade trade;
int emaFastHandle = INVALID_HANDLE;
int emaSlowHandle = INVALID_HANDLE;
datetime lastBarOpen = 0;

double ibHigh = 0.0, ibLow = 0.0, ibMid = 0.0;
bool ibHasData = false, ibReady = false, tradeTaken = false;
int nyDateKey = -1;

bool highBreakoutSeen = false, lowBreakoutSeen = false;
datetime highBreakoutTime = 0, lowBreakoutTime = 0;
double highExtensionFractal = 0.0, lowExtensionFractal = 0.0;
bool highFractalReady = false, lowFractalReady = false;
bool highReturnedToIB = false, lowReturnedToIB = false;
bool extensionInvalidated = false;

bool raidHighSeen = false, raidLowSeen = false;
int raidFirstSide = 0; // 1 = high first, -1 = low first
datetime raidHighTime = 0, raidLowTime = 0;
double raidHighExtreme = 0.0, raidLowExtreme = 0.0;
double raidHighFractal = 0.0, raidLowFractal = 0.0;
bool raidHighFractalReady = false, raidLowFractalReady = false;
bool raidHighReturnedToIB = false, raidLowReturnedToIB = false;
int raidHighCount = 0, raidLowCount = 0;

int NthSunday(const int year, const int month, const int nth)
{
   MqlDateTime d = {};
   d.year = year; d.mon = month; d.day = 1;
   datetime first = StructToTime(d);
   TimeToStruct(first, d);
   int firstSunday = 1 + ((7 - d.day_of_week) % 7);
   return firstSunday + 7 * (nth - 1);
}

bool NewYorkIsDst(const datetime utc)
{
   MqlDateTime u = {};
   TimeToStruct(utc, u);
   MqlDateTime start = {}, finish = {};
   start.year = u.year; start.mon = 3; start.day = NthSunday(u.year, 3, 2); start.hour = 7;
   finish.year = u.year; finish.mon = 11; finish.day = NthSunday(u.year, 11, 1); finish.hour = 6;
   return utc >= StructToTime(start) && utc < StructToTime(finish);
}

datetime ServerToNewYork(const datetime serverTime)
{
   datetime utc = serverTime - InpBrokerUtcOffsetHours * 3600;
   return utc + (NewYorkIsDst(utc) ? -4 : -5) * 3600;
}

void GetNewYorkParts(const datetime serverTime, MqlDateTime &ny)
{
   TimeToStruct(ServerToNewYork(serverTime), ny);
}

bool IsWeekday(const MqlDateTime &ny) { return ny.day_of_week >= 1 && ny.day_of_week <= 5; }
int MinutesOfDay(const MqlDateTime &ny) { return ny.hour * 60 + ny.min; }

void ResetDay()
{
   ibHigh = 0.0; ibLow = 0.0; ibMid = 0.0;
   ibHasData = false; ibReady = false; tradeTaken = false;
   highBreakoutSeen = false; lowBreakoutSeen = false;
   highBreakoutTime = 0; lowBreakoutTime = 0;
   highExtensionFractal = 0.0; lowExtensionFractal = 0.0;
   highFractalReady = false; lowFractalReady = false;
   highReturnedToIB = false; lowReturnedToIB = false;
   extensionInvalidated = false;
   raidHighSeen = false; raidLowSeen = false; raidFirstSide = 0;
   raidHighTime = 0; raidLowTime = 0;
   raidHighExtreme = 0.0; raidLowExtreme = 0.0;
   raidHighFractal = 0.0; raidLowFractal = 0.0;
   raidHighFractalReady = false; raidLowFractalReady = false;
   raidHighReturnedToIB = false; raidLowReturnedToIB = false;
   raidHighCount = 0; raidLowCount = 0;
}

bool IsFlat()
{
   return !PositionSelect(_Symbol);
}

bool GetEma(const int handle, const datetime barTime, double &value)
{
   int shift = iBarShift(_Symbol, InpEmaTimeframe, barTime, false);
   if(shift < 0) return false;
   datetime emaBarOpen = iTime(_Symbol, InpEmaTimeframe, shift);
   datetime signalBarClose = barTime + PeriodSeconds(_Period);
   datetime emaBarClose = emaBarOpen + PeriodSeconds(InpEmaTimeframe);
   // request.security(..., lookahead_off) does not expose an unfinished HTF bar.
   if(signalBarClose < emaBarClose) shift++;
   double data[1];
   if(CopyBuffer(handle, 0, shift, 1, data) != 1) return false;
   value = data[0];
   return value != EMPTY_VALUE;
}

bool PivotHighAt(const int shift, const int left, const int right, double &value)
{
   value = iHigh(_Symbol, _Period, shift);
   if(value == 0.0) return false;
   for(int i = 1; i <= left; i++)
      if(iHigh(_Symbol, _Period, shift + i) >= value) return false;
   for(int i = 1; i <= right; i++)
      if(iHigh(_Symbol, _Period, shift - i) > value) return false;
   return true;
}

bool PivotLowAt(const int shift, const int left, const int right, double &value)
{
   value = iLow(_Symbol, _Period, shift);
   if(value == 0.0) return false;
   for(int i = 1; i <= left; i++)
      if(iLow(_Symbol, _Period, shift + i) <= value) return false;
   for(int i = 1; i <= right; i++)
      if(iLow(_Symbol, _Period, shift - i) < value) return false;
   return true;
}

double NormalizeVolume(const double raw)
{
   double minVol = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxVol = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(step <= 0.0 || raw < minVol) return 0.0;
   double volume = MathFloor(raw / step + 1e-9) * step;
   volume = MathMax(minVol, MathMin(maxVol, volume));
   return NormalizeDouble(volume, 8);
}

double RiskVolume(const double entry, const double stop)
{
   double distance = MathAbs(entry - stop);
   double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE_LOSS);
   if(tickValue <= 0.0) tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   if(distance <= 0.0 || tickSize <= 0.0 || tickValue <= 0.0) return 0.0;
   double riskCash = InpRiskCapital * InpRiskPercent / 100.0;
   return NormalizeVolume(riskCash / ((distance / tickSize) * tickValue));
}

bool OpenTrade(const bool isLong, const double stop, const string comment)
{
   if(!InpAllowLiveTrading)
   {
      Print("SIGNAL ONLY: ", comment, " SL=", DoubleToString(stop, _Digits));
      return false;
   }
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick)) return false;
   double entry = isLong ? tick.ask : tick.bid;
   double tp = isLong ? entry + (entry - stop) * InpRewardRisk
                      : entry - (stop - entry) * InpRewardRisk;
   double volume = RiskVolume(entry, stop);
   if(volume <= 0.0)
   {
      Print("Order rejected: calculated volume is below broker minimum or symbol tick data is unavailable");
      return false;
   }
   double normalizedStop = NormalizeDouble(stop, _Digits);
   tp = NormalizeDouble(tp, _Digits);
   bool ok = isLong ? trade.Buy(volume, _Symbol, 0.0, normalizedStop, tp, comment)
                    : trade.Sell(volume, _Symbol, 0.0, normalizedStop, tp, comment);
   if(!ok) Print("Order failed: ", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
   return ok;
}

void MarkOrExecute(const bool execute, const bool isLong, const double stop, const string comment)
{
   if(execute) OpenTrade(isLong, stop, comment);
   tradeTaken = true; // One signal/position per New York trading day, matching Pine.
}

void ProcessClosedBar(const int shift, const bool execute)
{
   datetime barTime = iTime(_Symbol, _Period, shift);
   if(barTime == 0) return;
   MqlDateTime ny = {};
   GetNewYorkParts(barTime, ny);
   int dateKey = ny.year * 1000 + ny.day_of_year;
   if(dateKey != nyDateKey)
   {
      ResetDay();
      nyDateKey = dateKey;
   }
   if(!IsWeekday(ny)) return;

   int minute = MinutesOfDay(ny);
   int ibStart = InpIBStartHour * 60 + InpIBStartMinute;
   int ibEnd = InpIBEndHour * 60 + InpIBEndMinute;
   int tradeEnd = InpTradeEndHour * 60 + InpTradeEndMinute;
   bool inIB = minute >= ibStart && minute < ibEnd;
   bool inTrade = minute >= ibEnd && minute < tradeEnd;
   double high = iHigh(_Symbol, _Period, shift);
   double low = iLow(_Symbol, _Period, shift);
   double close = iClose(_Symbol, _Period, shift);
   double previousClose = iClose(_Symbol, _Period, shift + 1);

   if(inIB)
   {
      if(!ibHasData) { ibHigh = high; ibLow = low; ibHasData = true; }
      else { ibHigh = MathMax(ibHigh, high); ibLow = MathMin(ibLow, low); }
      return;
   }
   if(!ibReady && ibHasData && minute >= ibEnd)
   {
      ibMid = (ibHigh + ibLow) / 2.0;
      ibReady = true;
      Print("IB ready: H=", DoubleToString(ibHigh, _Digits), " L=", DoubleToString(ibLow, _Digits));
   }
   if(!ibReady || !inTrade || tradeTaken) return;

   bool flat = IsFlat();
   if(!flat && execute) return;

   bool highBreakout = !highBreakoutSeen && !lowBreakoutSeen &&
      (InpBreakoutNeedsClose ? close > ibHigh : high > ibHigh);
   bool lowBreakout = !highBreakoutSeen && !lowBreakoutSeen && !highBreakout &&
      (InpBreakoutNeedsClose ? close < ibLow : low < ibLow);
   if(highBreakout) { highBreakoutSeen = true; highBreakoutTime = barTime; }
   if(lowBreakout) { lowBreakoutSeen = true; lowBreakoutTime = barTime; }

   bool raidHighBeyond = InpBreakoutNeedsClose ? close > ibHigh : high > ibHigh;
   bool raidLowBeyond = InpBreakoutNeedsClose ? close < ibLow : low < ibLow;
   bool raidAmbiguous = raidHighBeyond && raidLowBeyond;
   int secondsPerBar = PeriodSeconds(_Period);
   bool raidHighNextWindow = raidFirstSide == -1 && raidHighSeen &&
      barTime == raidHighTime + secondsPerBar && !raidHighFractalReady;
   bool raidLowNextWindow = raidFirstSide == 1 && raidLowSeen &&
      barTime == raidLowTime + secondsPerBar && !raidLowFractalReady;
   bool nextBarRaidLong = !raidAmbiguous && raidHighNextWindow && close > ibHigh && high > raidHighExtreme;
   bool nextBarRaidShort = !raidAmbiguous && raidLowNextWindow && close < ibLow && low < raidLowExtreme;
   bool canStartRaidHigh = raidFirstSide == 0 || (raidHighSeen ? raidHighReturnedToIB : raidFirstSide == -1 && raidLowReturnedToIB);
   bool canStartRaidLow = raidFirstSide == 0 || (raidLowSeen ? raidLowReturnedToIB : raidFirstSide == 1 && raidHighReturnedToIB);
   bool raidHighBreakout = !raidAmbiguous && !raidHighNextWindow && canStartRaidHigh && raidHighBeyond;
   bool raidLowBreakout = !raidAmbiguous && !raidLowNextWindow && canStartRaidLow && raidLowBeyond;

   if(raidHighBreakout)
   {
      bool firstSideReraid = raidFirstSide == 1;
      raidHighSeen = true; if(raidFirstSide == 0) raidFirstSide = 1;
      raidHighTime = barTime; raidHighExtreme = high; raidHighCount++;
      raidHighFractal = 0.0; raidHighFractalReady = false; raidHighReturnedToIB = false;
      if(firstSideReraid)
      {
         raidLowSeen = false; raidLowTime = 0; raidLowExtreme = 0.0;
         raidLowFractal = 0.0; raidLowFractalReady = false; raidLowReturnedToIB = false;
      }
   }
   if(raidLowBreakout)
   {
      bool firstSideReraid = raidFirstSide == -1;
      raidLowSeen = true; if(raidFirstSide == 0) raidFirstSide = -1;
      raidLowTime = barTime; raidLowExtreme = low; raidLowCount++;
      raidLowFractal = 0.0; raidLowFractalReady = false; raidLowReturnedToIB = false;
      if(firstSideReraid)
      {
         raidHighSeen = false; raidHighTime = 0; raidHighExtreme = 0.0;
         raidHighFractal = 0.0; raidHighFractalReady = false; raidHighReturnedToIB = false;
      }
   }
   if(raidHighSeen && !raidHighReturnedToIB && high > ibHigh)
      raidHighExtreme = raidHighExtreme == 0.0 ? high : MathMax(raidHighExtreme, high);
   if(raidLowSeen && !raidLowReturnedToIB && low < ibLow)
      raidLowExtreme = raidLowExtreme == 0.0 ? low : MathMin(raidLowExtreme, low);
   if(raidHighSeen && !raidHighReturnedToIB && close <= ibHigh) raidHighReturnedToIB = true;
   if(raidLowSeen && !raidLowReturnedToIB && close >= ibLow) raidLowReturnedToIB = true;

   int pivotShift = shift + InpFractalRight;
   double pivotHigh = 0.0, pivotLow = 0.0;
   bool hasPivotHigh = PivotHighAt(pivotShift, InpFractalLeft, InpFractalRight, pivotHigh);
   bool hasPivotLow = PivotLowAt(pivotShift, InpFractalLeft, InpFractalRight, pivotLow);
   datetime pivotTime = iTime(_Symbol, _Period, pivotShift);
   if(highBreakoutSeen && hasPivotHigh && pivotTime >= highBreakoutTime && pivotHigh > ibHigh)
      { highExtensionFractal = pivotHigh; highFractalReady = true; }
   if(lowBreakoutSeen && hasPivotLow && pivotTime >= lowBreakoutTime && pivotLow < ibLow)
      { lowExtensionFractal = pivotLow; lowFractalReady = true; }
   if(raidHighSeen && hasPivotHigh && pivotTime >= raidHighTime && pivotHigh > ibHigh)
      { raidHighFractal = pivotHigh; raidHighFractalReady = true; }
   if(raidLowSeen && hasPivotLow && pivotTime >= raidLowTime && pivotLow < ibLow)
      { raidLowFractal = pivotLow; raidLowFractalReady = true; }

   bool highReturnedBefore = highReturnedToIB;
   bool lowReturnedBefore = lowReturnedToIB;
   bool longBosBeforeReturn = highBreakoutSeen && highFractalReady && !highReturnedBefore && close > highExtensionFractal;
   bool shortBosBeforeReturn = lowBreakoutSeen && lowFractalReady && !lowReturnedBefore && close < lowExtensionFractal;
   if(longBosBeforeReturn || shortBosBeforeReturn) extensionInvalidated = true;
   bool longExtensionSignal = highBreakoutSeen && !lowBreakoutSeen && highFractalReady &&
      highReturnedBefore && !extensionInvalidated && close > highExtensionFractal;
   bool shortExtensionSignal = lowBreakoutSeen && !highBreakoutSeen && lowFractalReady &&
      lowReturnedBefore && !extensionInvalidated && close < lowExtensionFractal;
   if(highBreakoutSeen && highFractalReady && !highReturnedToIB && !extensionInvalidated && low <= ibHigh)
      highReturnedToIB = true;
   if(lowBreakoutSeen && lowFractalReady && !lowReturnedToIB && !extensionInvalidated && high >= ibLow)
      lowReturnedToIB = true;

   bool directRaidShort = raidFirstSide == 1 && raidLowBreakout && !raidLowFractalReady && close < ibLow;
   bool directRaidLong = raidFirstSide == -1 && raidHighBreakout && !raidHighFractalReady && close > ibHigh;
   bool fractalRaidShort = raidFirstSide == 1 && raidLowSeen && raidLowFractalReady &&
      close < raidLowFractal && previousClose >= raidLowFractal;
   bool fractalRaidLong = raidFirstSide == -1 && raidHighSeen && raidHighFractalReady &&
      close > raidHighFractal && previousClose <= raidHighFractal;
   bool raidLongSignal = directRaidLong || nextBarRaidLong || fractalRaidLong;
   bool raidShortSignal = directRaidShort || nextBarRaidShort || fractalRaidShort;

   double fast = 0.0, slow = 0.0;
   if(!GetEma(emaFastHandle, barTime, fast) || !GetEma(emaSlowHandle, barTime, slow)) return;
   bool longAllowed = fast > slow;
   bool shortAllowed = fast < slow;
   double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickSize <= 0.0) tickSize = _Point;

   // Priority matches the Pine script: raid short, raid long, extension long, extension short.
   if(InpEnableRaidShort && raidShortSignal && shortAllowed && raidHighExtreme > close)
      MarkOrExecute(execute, false, raidHighExtreme + InpRaidStopBufferTicks * tickSize, "IB Raid Short");
   else if(InpEnableRaidLong && raidLongSignal && longAllowed && raidLowExtreme > 0.0 && raidLowExtreme < close)
      MarkOrExecute(execute, true, raidLowExtreme - InpRaidStopBufferTicks * tickSize, "IB Raid Long");
   else if(InpEnableExtensionLong && longExtensionSignal && longAllowed && ibLow < close)
      MarkOrExecute(execute, true, ibLow, "IB Extension Long");
   else if(InpEnableExtensionShort && shortExtensionSignal && shortAllowed && ibHigh > close)
      MarkOrExecute(execute, false, ibHigh, "IB Extension Short");
}

void ReplayToday()
{
   int bars = (int)MathMin(Bars(_Symbol, _Period) - 1, 600);
   if(bars <= 1) return;
   for(int shift = bars; shift >= 1; shift--)
      ProcessClosedBar(shift, false);
}

int OnInit()
{
   if(_Period != PERIOD_M5)
      Print("WARNING: strategy was designed for M5; current chart is ", EnumToString(_Period));
   if(InpFractalLeft < 1 || InpFractalRight < 1 || InpRiskCapital <= 0.0 ||
      InpRiskPercent <= 0.0 || InpRewardRisk <= 0.0)
      return INIT_PARAMETERS_INCORRECT;
   emaFastHandle = iMA(_Symbol, InpEmaTimeframe, InpEmaFastLength, 0, MODE_EMA, PRICE_CLOSE);
   emaSlowHandle = iMA(_Symbol, InpEmaTimeframe, InpEmaSlowLength, 0, MODE_EMA, PRICE_CLOSE);
   if(emaFastHandle == INVALID_HANDLE || emaSlowHandle == INVALID_HANDLE) return INIT_FAILED;
   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(InpMaxDeviationPoints);
   trade.SetTypeFillingBySymbol(_Symbol);
   lastBarOpen = iTime(_Symbol, _Period, 0);
   ReplayToday();
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   if(emaFastHandle != INVALID_HANDLE) IndicatorRelease(emaFastHandle);
   if(emaSlowHandle != INVALID_HANDLE) IndicatorRelease(emaSlowHandle);
}

void OnTick()
{
   datetime currentBar = iTime(_Symbol, _Period, 0);
   if(currentBar == 0 || currentBar == lastBarOpen) return;
   lastBarOpen = currentBar;
   ProcessClosedBar(1, true);
}
