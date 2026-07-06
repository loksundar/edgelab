"""Session-aware helpers shared by signal plugins.

All assume a tz-naive IST DatetimeIndex OHLCV frame that may span many days,
with the last row being the "current" candle.
"""

from __future__ import annotations

from datetime import date, time

import pandas as pd

MARKET_OPEN = time(9, 15)
LAST_ENTRY = time(14, 30)   # no fresh entries after this; square-off is 15:15


def current_day(df: pd.DataFrame) -> date:
    return df.index[-1].date()


def today(df: pd.DataFrame) -> pd.DataFrame:
    """Candles of the current (last) trading day."""
    return df[df.index.date == current_day(df)]


def prev_day(df: pd.DataFrame) -> pd.DataFrame:
    """Candles of the previous trading day (empty if none in frame)."""
    days = sorted({d for d in df.index.date})
    if len(days) < 2:
        return df.iloc[0:0]
    return df[df.index.date == days[-2]]


def entries_allowed(df: pd.DataFrame) -> bool:
    """True if the current candle is within the fresh-entry window.

    Daily candles (midnight timestamps) are always allowed — the intraday
    entry window doesn't apply to multi-day strategies."""
    t = df.index[-1].time()
    if t == time(0, 0):
        return True
    return MARKET_OPEN <= t <= LAST_ENTRY


def bars_into_session(df: pd.DataFrame) -> int:
    """Number of completed candles so far today, including the current one."""
    return len(today(df))


def opening_range(df: pd.DataFrame, minutes: int) -> tuple[float, float] | None:
    """(high, low) of the first `minutes` of today's session, or None if the
    session hasn't been open that long yet."""
    day = today(df)
    if day.empty:
        return None
    cutoff = day.index[0] + pd.Timedelta(minutes=minutes)
    window = day[day.index < cutoff]
    if window.empty or df.index[-1] < cutoff:
        return None
    return float(window["high"].max()), float(window["low"].min())
