"""Signal plugin registry — the heart of the app's modularity.

To add a new trading signal, create a file in this package with:

    from intraday.signals.registry import signal, SignalEvent

    @signal("my_new_signal", params={"lookback": 20})
    def my_new_signal(df, ctx):
        # df: OHLCV DataFrame up to "now" (last row = current candle)
        # return SignalEvent(...) to fire, or None to stay quiet
        ...

Nothing else to wire up: the backtester, scanner, notebooks, and paper bot
discover it automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import pandas as pd


@dataclass
class Context:
    """Everything a signal may want beyond the candle frame."""

    symbol: str
    interval: str
    params: dict = field(default_factory=dict)


@dataclass
class SignalEvent:
    """A fired signal: direction plus the exit plan."""

    side: str                     # "BUY" or "SELL" (short)
    entry: float                  # intended entry price
    stop: float                   # protective stop
    target: Optional[float] = None  # None => exit at square-off / stop only
    reason: str = ""              # human-readable, shows up in journals
    max_hold: Optional[int] = None  # daily strategies: exit after N bars (default 15)


SignalFunc = Callable[[pd.DataFrame, Context], Optional[SignalEvent]]


@dataclass
class SignalSpec:
    name: str
    func: SignalFunc
    params: dict
    description: str


_REGISTRY: dict[str, SignalSpec] = {}


def signal(name: str, params: dict | None = None) -> Callable[[SignalFunc], SignalFunc]:
    """Decorator that registers a signal function under a unique name."""

    def decorator(func: SignalFunc) -> SignalFunc:
        if name in _REGISTRY:
            raise ValueError(f"Signal {name!r} is already registered")
        _REGISTRY[name] = SignalSpec(
            name=name,
            func=func,
            params=params or {},
            description=(func.__doc__ or "").strip().splitlines()[0] if func.__doc__ else "",
        )
        return func

    return decorator


def get(name: str) -> SignalSpec:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown signal {name!r}. Registered: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def all_signals() -> dict[str, SignalSpec]:
    return dict(_REGISTRY)
