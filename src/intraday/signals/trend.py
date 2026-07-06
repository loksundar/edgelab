"""Trend-following signals (J. Welles Wilder 'New Concepts in Technical
Trading Systems' for ADX, Gerald Appel for MACD, Olivier Seban's Supertrend,
Brian Shannon for VWAP trend structure)."""

from __future__ import annotations

import pandas as pd

from intraday.signals import helpers, indicators
from intraday.signals.registry import Context, SignalEvent, signal


@signal("ema_cross_adx", params={"fast": 9, "slow": 21, "adx_min": 20})
def ema_cross_adx(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """9/21 EMA crossover taken only when ADX confirms a real trend (Wilder)."""
    if len(df) < 60 or not helpers.entries_allowed(df):
        return None
    close = df["close"]
    fast = indicators.ema(close, ctx.params.get("fast", 9))
    slow = indicators.ema(close, ctx.params.get("slow", 21))
    trend_strength = indicators.adx(df, 14).iloc[-1]
    if trend_strength < ctx.params.get("adx_min", 20):
        return None
    cur = float(close.iloc[-1])
    a = float(indicators.atr(df, 14).iloc[-1])
    crossed_up = fast.iloc[-2] <= slow.iloc[-2] and fast.iloc[-1] > slow.iloc[-1]
    crossed_dn = fast.iloc[-2] >= slow.iloc[-2] and fast.iloc[-1] < slow.iloc[-1]
    if crossed_up:
        return SignalEvent(side="BUY", entry=cur, stop=cur - 2 * a, target=cur + 3 * a,
                           reason=f"9/21 cross up, ADX={trend_strength:.0f}")
    if crossed_dn:
        return SignalEvent(side="SELL", entry=cur, stop=cur + 2 * a, target=cur - 3 * a,
                           reason=f"9/21 cross down, ADX={trend_strength:.0f}")
    return None


@signal("supertrend_flip", params={"period": 10, "multiplier": 3.0})
def supertrend_flip(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """Enter when Supertrend flips direction on the just-closed bar."""
    if len(df) < 60 or not helpers.entries_allowed(df):
        return None
    st = indicators.supertrend(df, ctx.params.get("period", 10),
                               ctx.params.get("multiplier", 3.0))
    cur = float(df["close"].iloc[-1])
    a = float(indicators.atr(df, 14).iloc[-1])
    if st.iloc[-2] == -1 and st.iloc[-1] == 1:
        return SignalEvent(side="BUY", entry=cur, stop=cur - 2 * a, target=cur + 3 * a,
                           reason="supertrend flip to up")
    if st.iloc[-2] == 1 and st.iloc[-1] == -1:
        return SignalEvent(side="SELL", entry=cur, stop=cur + 2 * a, target=cur - 3 * a,
                           reason="supertrend flip to down")
    return None


@signal("macd_signal_cross")
def macd_signal_cross(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """MACD/signal cross on the momentum side of zero (Appel): buy crosses
    below zero turning up, short crosses above zero turning down."""
    if len(df) < 60 or not helpers.entries_allowed(df):
        return None
    line, sig, _ = indicators.macd(df["close"])
    cur = float(df["close"].iloc[-1])
    a = float(indicators.atr(df, 14).iloc[-1])
    crossed_up = line.iloc[-2] <= sig.iloc[-2] and line.iloc[-1] > sig.iloc[-1]
    crossed_dn = line.iloc[-2] >= sig.iloc[-2] and line.iloc[-1] < sig.iloc[-1]
    if crossed_up and line.iloc[-1] < 0:
        return SignalEvent(side="BUY", entry=cur, stop=cur - 2 * a, target=cur + 3 * a,
                           reason="MACD cross up below zero")
    if crossed_dn and line.iloc[-1] > 0:
        return SignalEvent(side="SELL", entry=cur, stop=cur + 2 * a, target=cur - 3 * a,
                           reason="MACD cross down above zero")
    return None


@signal("vwap_pullback", params={"min_bars": 12})
def vwap_pullback(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """Trend-day pullback to VWAP that holds (Shannon): price has spent the
    whole session on one side of VWAP, touches it, and bounces."""
    if len(df) < 30 or not helpers.entries_allowed(df):
        return None
    day = helpers.today(df)
    if len(day) < ctx.params.get("min_bars", 12):
        return None
    vwap = indicators.session_vwap(df)
    day_vwap = vwap[vwap.index.date == day.index[0].date()]
    cur = df.iloc[-1]
    a = float(indicators.atr(df, 14).iloc[-1])
    # All closes so far above VWAP, current bar dips into it and closes green.
    above = (day["close"] >= day_vwap).all()
    below = (day["close"] <= day_vwap).all()
    touched = cur.low <= day_vwap.iloc[-1] <= cur.high
    if above and touched and cur.close > cur.open:
        return SignalEvent(side="BUY", entry=float(cur.close),
                           stop=float(day_vwap.iloc[-1] - a),
                           target=float(day["high"].max()),
                           reason="VWAP pullback hold (uptrend day)")
    if below and touched and cur.close < cur.open:
        return SignalEvent(side="SELL", entry=float(cur.close),
                           stop=float(day_vwap.iloc[-1] + a),
                           target=float(day["low"].min()),
                           reason="VWAP pullback hold (downtrend day)")
    return None
