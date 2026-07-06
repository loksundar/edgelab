"""Technical indicators used by signal plugins. Pure pandas/numpy, no TA-Lib.

All functions take/return pandas objects aligned to the input index and are
safe to call on a frame that includes multiple trading days.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift()
    return pd.concat(
        [df["high"] - df["low"],
         (df["high"] - prev_close).abs(),
         (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder's Average True Range."""
    return true_range(df).ewm(alpha=1 / period, adjust=False).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder's Average Directional Index (trend-strength filter)."""
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    tr_smooth = true_range(df).ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / tr_smooth
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / tr_smooth
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False).mean().fillna(0)


def bollinger(series: pd.Series, period: int = 20, num_std: float = 2.0):
    """Returns (middle, upper, lower, bandwidth)."""
    mid = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper, lower = mid + num_std * std, mid - num_std * std
    bandwidth = (upper - lower) / mid
    return mid, upper, lower, bandwidth


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal_period: int = 9):
    """Returns (macd_line, signal_line, histogram)."""
    line = ema(series, fast) - ema(series, slow)
    sig = ema(line, signal_period)
    return line, sig, line - sig


def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.Series:
    """Supertrend direction: +1 (uptrend) / -1 (downtrend) per bar."""
    hl2 = (df["high"] + df["low"]) / 2
    band_atr = atr(df, period)
    upper = (hl2 + multiplier * band_atr).to_numpy()
    lower = (hl2 - multiplier * band_atr).to_numpy()
    close = df["close"].to_numpy()

    n = len(df)
    direction = np.ones(n, dtype=int)
    final_upper = upper.copy()
    final_lower = lower.copy()
    for i in range(1, n):
        final_upper[i] = min(upper[i], final_upper[i - 1]) if close[i - 1] <= final_upper[i - 1] else upper[i]
        final_lower[i] = max(lower[i], final_lower[i - 1]) if close[i - 1] >= final_lower[i - 1] else lower[i]
        if close[i] > final_upper[i - 1]:
            direction[i] = 1
        elif close[i] < final_lower[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
    return pd.Series(direction, index=df.index)


def session_vwap(df: pd.DataFrame) -> pd.Series:
    """VWAP reset at the start of each trading day."""
    typical = (df["high"] + df["low"] + df["close"]) / 3
    pv = typical * df["volume"]
    day = df.index.date
    cum_pv = pv.groupby(day).cumsum()
    cum_vol = df["volume"].groupby(day).cumsum()
    return cum_pv / cum_vol.replace(0, np.nan)
