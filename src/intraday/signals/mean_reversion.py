"""Mean-reversion signals (Larry Connors 'Short Term Trading Strategies That
Work', Brian Shannon's VWAP work, classic gap-fade)."""

from __future__ import annotations

import pandas as pd

from intraday.signals import helpers, indicators
from intraday.signals.registry import Context, SignalEvent, signal


@signal("rsi2_extreme", params={"buy_below": 5, "sell_above": 95})
def rsi2_extreme(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """Connors RSI(2): buy panic dips inside an uptrend (price above 200-EMA),
    short euphoric pops inside a downtrend. Target: reversion to the 20-EMA."""
    if len(df) < 210 or not helpers.entries_allowed(df):
        return None
    close = df["close"]
    r = indicators.rsi(close, 2).iloc[-1]
    trend = indicators.ema(close, 200).iloc[-1]
    mean = indicators.ema(close, 20).iloc[-1]
    cur = float(close.iloc[-1])
    a = float(indicators.atr(df, 14).iloc[-1])
    if r < ctx.params.get("buy_below", 5) and cur > trend and mean > cur:
        return SignalEvent(side="BUY", entry=cur, stop=cur - 1.5 * a,
                           target=float(mean), reason=f"RSI(2)={r:.0f} in uptrend")
    if r > ctx.params.get("sell_above", 95) and cur < trend and mean < cur:
        return SignalEvent(side="SELL", entry=cur, stop=cur + 1.5 * a,
                           target=float(mean), reason=f"RSI(2)={r:.0f} in downtrend")
    return None


@signal("vwap_reversion", params={"stretch_atr": 2.5})
def vwap_reversion(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """Fade a price stretched far from session VWAP once a reversal candle
    prints; target is VWAP itself (Shannon-style AVWAP mean reversion)."""
    if len(df) < 30 or not helpers.entries_allowed(df):
        return None
    if helpers.bars_into_session(df) < 6:   # let VWAP stabilise first
        return None
    vwap = indicators.session_vwap(df)
    a = float(indicators.atr(df, 14).iloc[-1])
    if a <= 0:
        return None
    cur = df.iloc[-1]
    stretch = (cur.close - vwap.iloc[-1]) / a
    limit = ctx.params.get("stretch_atr", 2.5)
    if stretch <= -limit and cur.close > cur.open:      # stretched down, green bar
        return SignalEvent(side="BUY", entry=float(cur.close), stop=float(cur.low),
                           target=float(vwap.iloc[-1]),
                           reason=f"{-stretch:.1f} ATR below VWAP, reversal bar")
    if stretch >= limit and cur.close < cur.open:       # stretched up, red bar
        return SignalEvent(side="SELL", entry=float(cur.close), stop=float(cur.high),
                           target=float(vwap.iloc[-1]),
                           reason=f"{stretch:.1f} ATR above VWAP, reversal bar")
    return None


@signal("gap_fade", params={"min_gap_pct": 0.75, "decision_bar": 3})
def gap_fade(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """Fade an unfilled opening gap that stalls in the first 15 minutes;
    target is the previous day's close (gap fill)."""
    if not helpers.entries_allowed(df):
        return None
    prev = helpers.prev_day(df)
    day = helpers.today(df)
    bar_n = ctx.params.get("decision_bar", 3)
    if prev.empty or len(day) != bar_n:                 # decide exactly once
        return None
    prev_close = float(prev["close"].iloc[-1])
    day_open = float(day["open"].iloc[0])
    gap_pct = (day_open - prev_close) / prev_close * 100
    cur = df.iloc[-1]
    if gap_pct >= ctx.params.get("min_gap_pct", 0.75) and cur.close < day_open:
        stop = float(day["high"].max())
        # Needs room to the gap-fill target and a stop above entry.
        if stop <= cur.close or cur.close <= prev_close:
            return None
        return SignalEvent(side="SELL", entry=float(cur.close), stop=stop,
                           target=prev_close,
                           reason=f"fading +{gap_pct:.1f}% gap that stalled")
    if gap_pct <= -ctx.params.get("min_gap_pct", 0.75) and cur.close > day_open:
        stop = float(day["low"].min())
        if stop >= cur.close or cur.close >= prev_close:
            return None
        return SignalEvent(side="BUY", entry=float(cur.close), stop=stop,
                           target=prev_close,
                           reason=f"fading {gap_pct:.1f}% gap that stalled")
    return None


@signal("bollinger_reversion", params={"period": 20})
def bollinger_reversion(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """Close back inside the bands after a poke outside (Bollinger band snap)."""
    period = ctx.params.get("period", 20)
    if len(df) < period + 10 or not helpers.entries_allowed(df):
        return None
    mid, upper, lower, _ = indicators.bollinger(df["close"], period)
    prev, cur = df.iloc[-2], df.iloc[-1]
    # Reversion needs room: skip if price already crossed the mid band.
    if prev.close < lower.iloc[-2] and cur.close > lower.iloc[-1] and cur.close < mid.iloc[-1]:
        stop = float(min(prev.low, cur.low))
        if stop >= cur.close:   # bar closed at its low: no risk room
            return None
        return SignalEvent(side="BUY", entry=float(cur.close), stop=stop,
                           target=float(mid.iloc[-1]),
                           reason="re-entry above lower band")
    if prev.close > upper.iloc[-2] and cur.close < upper.iloc[-1] and cur.close > mid.iloc[-1]:
        stop = float(max(prev.high, cur.high))
        if stop <= cur.close:   # bar closed at its high: no risk room
            return None
        return SignalEvent(side="SELL", entry=float(cur.close), stop=stop,
                           target=float(mid.iloc[-1]),
                           reason="re-entry below upper band")
    return None
