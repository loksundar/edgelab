"""Broker abstraction.

Every broker (Angel One for data/paper today, Kite for live orders later)
implements this interface, so the rest of the app never imports a broker SDK
directly. Swapping brokers is a config change, not a code change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

import pandas as pd


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class Order:
    symbol: str
    side: Side
    qty: int
    price: float | None = None  # None => market order
    tag: str = ""


@dataclass
class OrderResult:
    order_id: str
    status: str
    message: str = ""


class Broker(ABC):
    """Minimal surface the app needs from any broker."""

    @abstractmethod
    def connect(self) -> None:
        """Authenticate and establish a session."""

    @abstractmethod
    def get_candles(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """Return OHLCV candles indexed by timestamp (tz-naive IST).

        Columns: open, high, low, close, volume.
        """

    @abstractmethod
    def place_order(self, order: Order) -> OrderResult:
        """Place an intraday (MIS) order."""

    @abstractmethod
    def ltp(self, symbol: str) -> float:
        """Last traded price."""
