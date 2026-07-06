"""Candlestick reversal patterns (Steve Nison, 'Japanese Candlestick Charting
Techniques'). All fire only on the just-closed candle, with a simple trend
filter so reversals appear in context rather than in chop."""

from __future__ import annotations

import pandas as pd

from intraday.signals import helpers, indicators
from intraday.signals.registry import Context, SignalEvent, signal

MIN_BARS = 25


def _bodies(df: pd.DataFrame):
    o, c = df["open"], df["close"]
    return (c - o).abs(), df["high"] - df["low"]


def _downtrend(df: pd.DataFrame) -> bool:
    return df["close"].iloc[-1] < indicators.ema(df["close"], 20).iloc[-1]


def _uptrend(df: pd.DataFrame) -> bool:
    return df["close"].iloc[-1] > indicators.ema(df["close"], 20).iloc[-1]


@signal("bullish_engulfing")
def bullish_engulfing(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """Bullish engulfing after a dip below the 20-EMA (Nison)."""
    if len(df) < MIN_BARS or not helpers.entries_allowed(df):
        return None
    prev, cur = df.iloc[-2], df.iloc[-1]
    if (
        _downtrend(df.iloc[:-1])
        and prev.close < prev.open                      # red candle
        and cur.close > cur.open                        # green candle
        and cur.open <= prev.close and cur.close >= prev.open  # engulfs body
    ):
        stop = float(min(cur.low, prev.low))
        risk = cur.close - stop
        if risk <= 0:
            return None
        return SignalEvent(side="BUY", entry=float(cur.close), stop=stop,
                           target=float(cur.close + 2 * risk),
                           reason="bullish engulfing below 20-EMA")
    return None


@signal("bearish_engulfing")
def bearish_engulfing(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """Bearish engulfing after a run above the 20-EMA (Nison)."""
    if len(df) < MIN_BARS or not helpers.entries_allowed(df):
        return None
    prev, cur = df.iloc[-2], df.iloc[-1]
    if (
        _uptrend(df.iloc[:-1])
        and prev.close > prev.open
        and cur.close < cur.open
        and cur.open >= prev.close and cur.close <= prev.open
    ):
        stop = float(max(cur.high, prev.high))
        risk = stop - cur.close
        if risk <= 0:
            return None
        return SignalEvent(side="SELL", entry=float(cur.close), stop=stop,
                           target=float(cur.close - 2 * risk),
                           reason="bearish engulfing above 20-EMA")
    return None


@signal("hammer")
def hammer(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """Hammer at a session low: long lower shadow, small body (Nison)."""
    if len(df) < MIN_BARS or not helpers.entries_allowed(df):
        return None
    cur = df.iloc[-1]
    body = abs(cur.close - cur.open)
    lower_shadow = min(cur.close, cur.open) - cur.low
    upper_shadow = cur.high - max(cur.close, cur.open)
    day = helpers.today(df)
    if (
        _downtrend(df.iloc[:-1])
        and body > 0
        and lower_shadow >= 2 * body
        and upper_shadow <= 0.5 * body
        and cur.low <= day["low"].min()                 # at the day's low
    ):
        risk = cur.close - cur.low
        if risk <= 0:
            return None
        return SignalEvent(side="BUY", entry=float(cur.close), stop=float(cur.low),
                           target=float(cur.close + 2 * risk),
                           reason="hammer at session low")
    return None


@signal("shooting_star")
def shooting_star(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """Shooting star at a session high: long upper shadow, small body (Nison)."""
    if len(df) < MIN_BARS or not helpers.entries_allowed(df):
        return None
    cur = df.iloc[-1]
    body = abs(cur.close - cur.open)
    upper_shadow = cur.high - max(cur.close, cur.open)
    lower_shadow = min(cur.close, cur.open) - cur.low
    day = helpers.today(df)
    if (
        _uptrend(df.iloc[:-1])
        and body > 0
        and upper_shadow >= 2 * body
        and lower_shadow <= 0.5 * body
        and cur.high >= day["high"].max()
    ):
        risk = cur.high - cur.close
        if risk <= 0:
            return None
        return SignalEvent(side="SELL", entry=float(cur.close), stop=float(cur.high),
                           target=float(cur.close - 2 * risk),
                           reason="shooting star at session high")
    return None


@signal("morning_star")
def morning_star(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """Morning star: red candle, small-body pause, strong green recovery (Nison)."""
    if len(df) < MIN_BARS or not helpers.entries_allowed(df):
        return None
    a, b, c = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    range_a = a.high - a.low
    if range_a <= 0:
        return None
    if (
        _downtrend(df.iloc[:-2])
        and a.close < a.open and (a.open - a.close) > 0.5 * range_a   # strong red
        and abs(b.close - b.open) < 0.3 * range_a                     # small pause
        and c.close > c.open and c.close > (a.open + a.close) / 2     # recovers >50%
    ):
        stop = float(min(a.low, b.low, c.low))
        risk = c.close - stop
        if risk <= 0:
            return None
        return SignalEvent(side="BUY", entry=float(c.close), stop=stop,
                           target=float(c.close + 2 * risk),
                           reason="morning star")
    return None


@signal("evening_star")
def evening_star(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """Evening star: green candle, small-body pause, strong red reversal (Nison)."""
    if len(df) < MIN_BARS or not helpers.entries_allowed(df):
        return None
    a, b, c = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    range_a = a.high - a.low
    if range_a <= 0:
        return None
    if (
        _uptrend(df.iloc[:-2])
        and a.close > a.open and (a.close - a.open) > 0.5 * range_a
        and abs(b.close - b.open) < 0.3 * range_a
        and c.close < c.open and c.close < (a.open + a.close) / 2
    ):
        stop = float(max(a.high, b.high, c.high))
        risk = stop - c.close
        if risk <= 0:
            return None
        return SignalEvent(side="SELL", entry=float(c.close), stop=stop,
                           target=float(c.close - 2 * risk),
                           reason="evening star")
    return None
