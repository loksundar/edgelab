"""Pivot-based signals: floor-trader pivots and CPR (Central Pivot Range,
popularised in India by Frank Ochoa's 'Secrets of a Pivot Boss')."""

from __future__ import annotations

import pandas as pd

from intraday.signals import helpers, indicators
from intraday.signals.registry import Context, SignalEvent, signal


def _pivots(prev: pd.DataFrame) -> dict[str, float]:
    h, l, c = float(prev["high"].max()), float(prev["low"].min()), float(prev["close"].iloc[-1])
    p = (h + l + c) / 3
    bc = (h + l) / 2
    tc = 2 * p - bc
    return {
        "P": p, "BC": min(bc, tc), "TC": max(bc, tc),
        "R1": 2 * p - l, "S1": 2 * p - h,
        "prev_high": h, "prev_low": l,
    }


@signal("cpr_breakout", params={"narrow_pct": 0.3})
def cpr_breakout(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """Narrow-CPR day breakout (Ochoa): a tight central pivot range signals a
    coiled market; first close beyond it rides the expansion."""
    if len(df) < 25 or not helpers.entries_allowed(df):
        return None
    prev = helpers.prev_day(df)
    if prev.empty:
        return None
    piv = _pivots(prev)
    width_pct = (piv["TC"] - piv["BC"]) / piv["P"] * 100
    if width_pct > ctx.params.get("narrow_pct", 0.3):
        return None
    cur = df.iloc[-1]
    prev_close = df["close"].iloc[-2]
    a = float(indicators.atr(df, 14).iloc[-1])
    if prev_close <= piv["TC"] < cur.close:
        return SignalEvent(side="BUY", entry=float(cur.close), stop=float(piv["BC"] - a / 2),
                           target=float(piv["R1"]),
                           reason=f"narrow CPR ({width_pct:.2f}%) break up")
    if prev_close >= piv["BC"] > cur.close:
        return SignalEvent(side="SELL", entry=float(cur.close), stop=float(piv["TC"] + a / 2),
                           target=float(piv["S1"]),
                           reason=f"narrow CPR ({width_pct:.2f}%) break down")
    return None


@signal("pivot_bounce", params={"tolerance_atr": 0.3})
def pivot_bounce(df: pd.DataFrame, ctx: Context) -> SignalEvent | None:
    """Rejection candle off S1 (long) or R1 (short) — floor-trader pivot play."""
    if len(df) < 25 or not helpers.entries_allowed(df):
        return None
    prev = helpers.prev_day(df)
    if prev.empty:
        return None
    piv = _pivots(prev)
    cur = df.iloc[-1]
    a = float(indicators.atr(df, 14).iloc[-1])
    tol = ctx.params.get("tolerance_atr", 0.3) * a
    # Long: bar tags S1 within tolerance and closes green above it,
    # with the pivot target still overhead (room to run).
    if (abs(cur.low - piv["S1"]) <= tol and cur.close > cur.open
            and cur.close > piv["S1"] and cur.close < piv["P"]):
        return SignalEvent(side="BUY", entry=float(cur.close),
                           stop=float(cur.low - a / 2), target=float(piv["P"]),
                           reason="bounce off S1")
    if (abs(cur.high - piv["R1"]) <= tol and cur.close < cur.open
            and cur.close < piv["R1"] and cur.close > piv["P"]):
        return SignalEvent(side="SELL", entry=float(cur.close),
                           stop=float(cur.high + a / 2), target=float(piv["P"]),
                           reason="rejection at R1")
    return None
