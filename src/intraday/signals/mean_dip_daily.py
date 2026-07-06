"""User's mean-dip algo at DAILY timeframe: a range-bound stock trading well
below its multi-week average gets bought and held (CNC delivery) until it
reverts to that mean, stops out, or times out after ~3 weeks.

Long-only: you cannot carry a short overnight in the cash segment.

Variants: 2% and 3% dips below a 60-session mean, with and without a
green-day confirmation.
"""

from __future__ import annotations

import pandas as pd

from intraday.signals import helpers
from intraday.signals.registry import Context, SignalEvent, signal

MEAN_BARS = 60         # sessions in the mean (~3 months)
MAX_TREND_PCT = 3.0    # how flat the mean must be to call the stock range-bound


def _mean_dip_daily(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    dip_pct = ctx.params["dip_pct"]
    confirm = ctx.params.get("confirm", False)
    if len(df) < MEAN_BARS + 5 or not helpers.entries_allowed(df):
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
    if cur.close >= trigger:
        return None
    if confirm:
        # Wait for the turn: a green day while below the trigger.
        fired = prev.close < prev.open and cur.close > cur.open
    else:
        # Plain crossing: first close below the trigger.
        fired = prev.close >= trigger
    if not fired:
        return None
    stop = float(cur.close - (mean - cur.close))   # symmetric 1R below entry
    if stop >= cur.close or mean <= cur.close:
        return None
    return SignalEvent(
        side="BUY", entry=float(cur.close), stop=stop, target=mean,
        reason=f"{(mean - cur.close) / mean * 100:.1f}% below {MEAN_BARS}-day mean",
    )


@signal("mean_dip_d2", params={"dip_pct": 2.0})
def mean_dip_d2(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """Daily: buy 2% below a flat 60-day mean, hold to the mean."""
    return _mean_dip_daily(df, ctx)


@signal("mean_dip_d3", params={"dip_pct": 3.0})
def mean_dip_d3(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """Daily: buy 3% below a flat 60-day mean, hold to the mean."""
    return _mean_dip_daily(df, ctx)


@signal("mean_dip_d2_confirm", params={"dip_pct": 2.0, "confirm": True})
def mean_dip_d2_confirm(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """Daily: 2% dip + green-day confirmation before buying."""
    return _mean_dip_daily(df, ctx)


@signal("mean_dip_d3_confirm", params={"dip_pct": 3.0, "confirm": True})
def mean_dip_d3_confirm(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """Daily: 3% dip + green-day confirmation before buying."""
    return _mean_dip_daily(df, ctx)
