"""User's algo: range-bound stocks oscillate around a stable value — buy the
dip below that mean, sell the recovery back to it.

Mechanics:
- "mean" = rolling mean of close over the last ~5 sessions of bars
- only trade symbols currently RANGE-BOUND: the mean itself must be flat
  (first half vs second half of the window differ by less than max_trend_pct)
- BUY when price drops dip_pct below the mean; target = the mean;
  stop = an equal distance below entry (1R:1R geometry)

Registered in two variants so both dip depths ride one backtest run:
mean_dip_050 (0.5% dip) and mean_dip_100 (1.0% dip).
"""

from __future__ import annotations

import pandas as pd

from intraday.signals import helpers
from intraday.signals.registry import Context, SignalEvent, signal

MEAN_BARS = 375        # ~5 sessions of 5-minute bars
MAX_TREND_PCT = 0.5    # how flat the mean must be to call the stock range-bound


def _mean_dip(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    dip_pct = ctx.params["dip_pct"]
    if len(df) < MEAN_BARS or not helpers.entries_allowed(df):
        return None
    closes = df["close"].iloc[-MEAN_BARS:]
    mean = float(closes.mean())

    # Range-bound filter: the level must be stable across the window.
    first_half = float(closes.iloc[: MEAN_BARS // 2].mean())
    second_half = float(closes.iloc[MEAN_BARS // 2:].mean())
    if abs(second_half - first_half) / mean * 100 > ctx.params.get(
        "max_trend_pct", MAX_TREND_PCT
    ):
        return None

    cur = float(df["close"].iloc[-1])
    prev = float(df["close"].iloc[-2])
    trigger = mean * (1 - dip_pct / 100)
    # First bar closing below the trigger (not already deep in the hole).
    if cur < trigger and prev >= trigger:
        stop = cur - (mean - cur)          # symmetric 1R below entry
        if stop >= cur or mean <= cur:
            return None
        return SignalEvent(
            side="BUY", entry=cur, stop=float(stop), target=mean,
            reason=f"{(mean - cur) / mean * 100:.2f}% below {MEAN_BARS}-bar mean",
        )
    return None


def _mean_dip_confirmed(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """Same dip logic, but wait for the bounce to start: enter on the first
    GREEN bar while below the trigger, stop under the dip's low, target the
    mean. Entries only in the 10:00-13:59 window (edges of the session were
    net-negative across every signal tested)."""
    dip_pct = ctx.params["dip_pct"]
    if len(df) < MEAN_BARS or not helpers.entries_allowed(df):
        return None
    ts = df.index[-1]
    if not (10 <= ts.hour < 14):
        return None
    closes = df["close"].iloc[-MEAN_BARS:]
    mean = float(closes.mean())
    first_half = float(closes.iloc[: MEAN_BARS // 2].mean())
    second_half = float(closes.iloc[MEAN_BARS // 2:].mean())
    if abs(second_half - first_half) / mean * 100 > ctx.params.get(
        "max_trend_pct", MAX_TREND_PCT
    ):
        return None
    trigger = mean * (1 - dip_pct / 100)
    cur, prev = df.iloc[-1], df.iloc[-2]
    # Below the trigger, previous bar red (the dip), current bar green (the turn).
    if cur.close < trigger and prev.close < prev.open and cur.close > cur.open:
        dip_low = float(df["low"].iloc[-6:].min())   # low of the dip leg
        if dip_low >= cur.close or mean <= cur.close:
            return None
        return SignalEvent(
            side="BUY", entry=float(cur.close), stop=dip_low, target=mean,
            reason=f"confirmed bounce {(mean - cur.close) / mean * 100:.2f}% below mean",
        )
    return None


@signal("mean_dip_050", params={"dip_pct": 0.5, "max_trend_pct": MAX_TREND_PCT})
def mean_dip_050(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """Buy 0.5% dips below a flat multi-day mean; sell at the mean."""
    return _mean_dip(df, ctx)


@signal("mean_dip_050_confirm", params={"dip_pct": 0.5, "max_trend_pct": MAX_TREND_PCT})
def mean_dip_050_confirm(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """0.5% dip + green-bar confirmation + mid-day window."""
    return _mean_dip_confirmed(df, ctx)


@signal("mean_dip_100_confirm", params={"dip_pct": 1.0, "max_trend_pct": MAX_TREND_PCT})
def mean_dip_100_confirm(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """1.0% dip + green-bar confirmation + mid-day window."""
    return _mean_dip_confirmed(df, ctx)


@signal("mean_dip_100", params={"dip_pct": 1.0, "max_trend_pct": MAX_TREND_PCT})
def mean_dip_100(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """Buy 1.0% dips below a flat multi-day mean; sell at the mean."""
    return _mean_dip(df, ctx)
