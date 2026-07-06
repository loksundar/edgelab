"""Breakout signals (Toby Crabel 'Day Trading with Short Term Price Patterns',
John Bollinger 'Bollinger on Bollinger Bands')."""

from __future__ import annotations

import pandas as pd

from intraday.signals import helpers, indicators
from intraday.signals.registry import Context, SignalEvent, signal


@signal("orb_breakout", params={"range_minutes": 15, "volume_mult": 1.5})
def orb_breakout(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """Opening Range Breakout with volume confirmation (Crabel)."""
    if not helpers.entries_allowed(df):
        return None
    minutes = ctx.params.get("range_minutes", 15)
    rng = helpers.opening_range(df, minutes)
    if rng is None or len(df) < 25:
        return None
    orb_high, orb_low = rng
    cur = df.iloc[-1]
    prev_close = df["close"].iloc[-2]
    vol_avg = df["volume"].iloc[-21:-1].mean()
    vol_ok = cur.volume >= ctx.params.get("volume_mult", 1.5) * vol_avg
    height = orb_high - orb_low
    if height <= 0 or not vol_ok:
        return None
    # First close beyond the range (previous close still inside).
    if cur.close > orb_high and prev_close <= orb_high:
        return SignalEvent(side="BUY", entry=float(cur.close), stop=float(orb_low),
                           target=float(cur.close + height),
                           reason=f"ORB{minutes} breakout up")
    if cur.close < orb_low and prev_close >= orb_low:
        return SignalEvent(side="SELL", entry=float(cur.close), stop=float(orb_high),
                           target=float(cur.close - height),
                           reason=f"ORB{minutes} breakout down")
    return None


@signal("prev_day_high_break", params={"atr_stop_mult": 1.5})
def prev_day_high_break(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """First close above the previous day's high (classic momentum breakout)."""
    if len(df) < 25 or not helpers.entries_allowed(df):
        return None
    prev = helpers.prev_day(df)
    if prev.empty:
        return None
    pdh = float(prev["high"].max())
    cur_close = df["close"].iloc[-1]
    if df["close"].iloc[-2] <= pdh < cur_close:
        a = indicators.atr(df, 14).iloc[-1]
        stop = cur_close - ctx.params.get("atr_stop_mult", 1.5) * a
        return SignalEvent(side="BUY", entry=float(cur_close), stop=float(stop),
                           target=float(cur_close + 2 * (cur_close - stop)),
                           reason="close above previous day high")
    return None


@signal("prev_day_low_break", params={"atr_stop_mult": 1.5})
def prev_day_low_break(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """First close below the previous day's low (downside momentum)."""
    if len(df) < 25 or not helpers.entries_allowed(df):
        return None
    prev = helpers.prev_day(df)
    if prev.empty:
        return None
    pdl = float(prev["low"].min())
    cur_close = df["close"].iloc[-1]
    if df["close"].iloc[-2] >= pdl > cur_close:
        a = indicators.atr(df, 14).iloc[-1]
        stop = cur_close + ctx.params.get("atr_stop_mult", 1.5) * a
        return SignalEvent(side="SELL", entry=float(cur_close), stop=float(stop),
                           target=float(cur_close - 2 * (stop - cur_close)),
                           reason="close below previous day low")
    return None


@signal("bollinger_squeeze_break", params={"period": 20, "squeeze_pct": 0.2})
def bollinger_squeeze_break(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """Volatility squeeze then band break (Bollinger): bandwidth in the lowest
    20% of the last 100 bars, price closes outside a band."""
    period = ctx.params.get("period", 20)
    if len(df) < 120 or not helpers.entries_allowed(df):
        return None
    mid, upper, lower, bandwidth = indicators.bollinger(df["close"], period)
    was_squeezed = bandwidth.iloc[-2] <= bandwidth.iloc[-101:-1].quantile(
        ctx.params.get("squeeze_pct", 0.2)
    )
    if not was_squeezed:
        return None
    cur = df.iloc[-1]
    if cur.close > upper.iloc[-1]:
        stop = float(mid.iloc[-1])
        risk = cur.close - stop
        return SignalEvent(side="BUY", entry=float(cur.close), stop=stop,
                           target=float(cur.close + 2 * risk),
                           reason="squeeze break up")
    if cur.close < lower.iloc[-1]:
        stop = float(mid.iloc[-1])
        risk = stop - cur.close
        return SignalEvent(side="SELL", entry=float(cur.close), stop=stop,
                           target=float(cur.close - 2 * risk),
                           reason="squeeze break down")
    return None


@signal("volume_spike_break", params={"vol_mult": 3.0, "lookback": 20})
def volume_spike_break(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """New N-bar high/low on a 3x volume spike (momentum ignition)."""
    lookback = ctx.params.get("lookback", 20)
    if len(df) < lookback + 5 or not helpers.entries_allowed(df):
        return None
    cur = df.iloc[-1]
    vol_avg = df["volume"].iloc[-(lookback + 1):-1].mean()
    if cur.volume < ctx.params.get("vol_mult", 3.0) * vol_avg:
        return None
    window = df.iloc[-(lookback + 1):-1]
    a = indicators.atr(df, 14).iloc[-1]
    if cur.close > window["high"].max() and cur.close > cur.open:
        return SignalEvent(side="BUY", entry=float(cur.close),
                           stop=float(cur.close - 1.5 * a),
                           target=float(cur.close + 3 * a),
                           reason="volume spike + new high")
    if cur.close < window["low"].min() and cur.close < cur.open:
        return SignalEvent(side="SELL", entry=float(cur.close),
                           stop=float(cur.close + 1.5 * a),
                           target=float(cur.close - 3 * a),
                           reason="volume spike + new low")
    return None
