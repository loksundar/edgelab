"""Daily-bar strategy battery: the documented swing/position families.

- donchian_breakout_d : 55-day channel breakout, ride with wide ATR stop
  (Richard Dennis' Turtles / classic trend following)
- high52_momentum_d   : new high near the 6-month high on volume
  (George­-soros-era momentum literature; "6-month high effect")
- rsi2_daily          : RSI(2) panic dip inside a medium-term uptrend
  (Larry Connors, daily variant — his documented configuration)
- three_down_days     : 3 consecutive red closes in an uptrend, snap-back buy
  (short-term reversal effect)

All long-only (cash segment). WINDOW is 450 bars, so a full 252-day lookback
plus indicators fits.
"""

from __future__ import annotations

import pandas as pd

from intraday.signals import helpers, indicators
from intraday.signals.registry import Context, SignalEvent, signal


def _daily(df: pd.DataFrame) -> bool:
    return len(df) > 0 and df.index[-1].time().hour == 0


@signal("donchian_breakout_d", params={"entry_days": 55, "atr_stop": 2.5, "hold": 40})
def donchian_breakout_d(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """Turtle-style: close above the 55-day high, wide stop, let it run."""
    n = ctx.params.get("entry_days", 55)
    if not _daily(df) or len(df) < n + 20:
        return None
    cur = df.iloc[-1]
    prior_high = float(df["high"].iloc[-(n + 1):-1].max())
    if cur.close <= prior_high or df["close"].iloc[-2] > prior_high:
        return None
    a = float(indicators.atr(df, 20).iloc[-1])
    stop = float(cur.close - ctx.params.get("atr_stop", 2.5) * a)
    if stop >= cur.close:
        return None
    return SignalEvent(side="BUY", entry=float(cur.close), stop=stop, target=None,
                       max_hold=ctx.params.get("hold", 40),
                       reason=f"55d breakout above {prior_high:.1f}")


@signal("high52_momentum_d", params={"within_pct": 2.0, "vol_mult": 1.5, "hold": 40})
def high52_momentum_d(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """Buy strength near the 6-month high with a volume push."""
    if not _daily(df) or len(df) < 140:
        return None
    cur = df.iloc[-1]
    high52 = float(df["high"].iloc[-126:].max())
    near = cur.close >= high52 * (1 - ctx.params.get("within_pct", 2.0) / 100)
    fresh = df["close"].iloc[-2] < high52 * (1 - ctx.params.get("within_pct", 2.0) / 100)
    vol_ok = cur.volume >= ctx.params.get("vol_mult", 1.5) * df["volume"].iloc[-21:-1].mean()
    if not (near and fresh and vol_ok and cur.close > cur.open):
        return None
    a = float(indicators.atr(df, 20).iloc[-1])
    stop = float(cur.close - 2.5 * a)
    if stop >= cur.close:
        return None
    return SignalEvent(side="BUY", entry=float(cur.close), stop=stop, target=None,
                       max_hold=ctx.params.get("hold", 40),
                       reason="approach to 6-month high on volume")


@signal("rsi2_daily", params={"rsi_max": 10, "hold": 6})
def rsi2_daily(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """Connors: close > 100-day SMA, RSI(2) < 10 — buy panic, exit in days."""
    if not _daily(df) or len(df) < 110:
        return None
    closes = df["close"]
    cur = float(closes.iloc[-1])
    sma200 = float(closes.rolling(100).mean().iloc[-1])
    r2 = float(indicators.rsi(closes, 2).iloc[-1])
    if cur <= sma200 or r2 >= ctx.params.get("rsi_max", 10):
        return None
    a = float(indicators.atr(df, 20).iloc[-1])
    stop = float(cur - 2 * a)
    target = float(closes.rolling(5).mean().iloc[-1] + a)  # snap back above 5d mean
    if stop >= cur or target <= cur:
        return None
    return SignalEvent(side="BUY", entry=cur, stop=stop, target=target,
                       max_hold=ctx.params.get("hold", 6),
                       reason=f"RSI(2)={r2:.0f} above 100-SMA")


@signal("three_down_days", params={"hold": 5})
def three_down_days(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """Three straight red closes in a medium-term uptrend; buy the snap-back."""
    if not _daily(df) or len(df) < 110:
        return None
    closes = df["close"]
    cur = float(closes.iloc[-1])
    sma200 = float(closes.rolling(100).mean().iloc[-1])
    c = closes.iloc[-4:].to_list()
    three_red = c[1] < c[0] and c[2] < c[1] and c[3] < c[2]
    if cur <= sma200 or not three_red:
        return None
    a = float(indicators.atr(df, 20).iloc[-1])
    stop = float(cur - 2 * a)
    target = float(closes.iloc[-4])   # back to where the slide started
    if stop >= cur or target <= cur:
        return None
    return SignalEvent(side="BUY", entry=cur, stop=stop, target=target,
                       max_hold=ctx.params.get("hold", 5),
                       reason="3 down days above 100-SMA")
