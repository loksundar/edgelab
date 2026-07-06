"""Angel One SmartAPI broker: historical candles, LTP, and (later) orders."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

import pandas as pd
import pyotp

from intraday.brokers.base import Broker, Order, OrderResult, Side
from intraday.config import credentials
from intraday.data import instruments

log = logging.getLogger(__name__)

# SmartAPI caps the span of one getCandleData call, per interval (days).
MAX_DAYS_PER_REQUEST = {
    "ONE_MINUTE": 30,
    "THREE_MINUTE": 60,
    "FIVE_MINUTE": 100,
    "TEN_MINUTE": 100,
    "FIFTEEN_MINUTE": 200,
    "THIRTY_MINUTE": 200,
    "ONE_HOUR": 400,
    "ONE_DAY": 2000,
}

# Historical API rate limit is nominally 3 req/sec, but sustained bursts
# still trip AB1021 "Too many requests" — stay well under it.
MIN_SECONDS_BETWEEN_CALLS = 0.8


class AngelOneBroker(Broker):
    def __init__(self) -> None:
        self._api = None
        self._tokens: dict[str, str] = {}
        self._last_call = 0.0

    def connect(self) -> None:
        from SmartApi import SmartConnect

        creds = credentials()
        creds.validate()
        self._api = SmartConnect(api_key=creds.api_key)
        totp_now = pyotp.TOTP(creds.totp_secret).now()
        session = self._api.generateSession(creds.client_code, creds.pin, totp_now)
        if not session.get("status"):
            raise RuntimeError(f"Angel One login failed: {session.get('message')}")
        log.info("Angel One session established for %s", creds.client_code)

    def _require_api(self):
        if self._api is None:
            raise RuntimeError("Broker not connected. Call connect() first.")
        return self._api

    def _token(self, symbol: str) -> str:
        if symbol not in self._tokens:
            self._tokens.update(instruments.token_map([symbol]))
        return self._tokens[symbol]

    def _throttle(self) -> None:
        wait = MIN_SECONDS_BETWEEN_CALLS - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def get_candles(
        self, symbol: str, interval: str, start: datetime, end: datetime
    ) -> pd.DataFrame:
        """Fetch candles, transparently chunking requests to API span limits."""
        api = self._require_api()
        if interval not in MAX_DAYS_PER_REQUEST:
            raise ValueError(f"Unknown interval {interval!r}")
        token = self._token(symbol)
        chunk = timedelta(days=MAX_DAYS_PER_REQUEST[interval])

        frames: list[pd.DataFrame] = []
        cursor = start
        while cursor < end:
            chunk_end = min(cursor + chunk, end)
            rows = self._fetch_chunk(api, token, interval, cursor, chunk_end)
            if rows:
                frames.append(pd.DataFrame(
                    rows, columns=["timestamp", "open", "high", "low", "close", "volume"]
                ))
            cursor = chunk_end
        if not frames:
            return pd.DataFrame(
                columns=["open", "high", "low", "close", "volume"],
                index=pd.DatetimeIndex([], name="timestamp"),
            )
        df = pd.concat(frames, ignore_index=True)
        # API returns IST timestamps with +05:30 offset; store tz-naive IST.
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
        df = df.drop_duplicates("timestamp").set_index("timestamp").sort_index()
        return df

    def _fetch_chunk(self, api, token: str, interval: str,
                     start: datetime, end: datetime, retries: int = 3) -> list:
        params = {
            "exchange": "NSE",
            "symboltoken": token,
            "interval": interval,
            "fromdate": start.strftime("%Y-%m-%d %H:%M"),
            "todate": end.strftime("%Y-%m-%d %H:%M"),
        }
        for attempt in range(1, retries + 1):
            self._throttle()
            try:
                resp = api.getCandleData(params)
                if resp.get("status"):
                    return resp.get("data") or []
                message = resp.get("message", "unknown error")
            except Exception as exc:  # network hiccups, rate-limit rejections
                message = str(exc)
            if attempt < retries:
                # Rate-limit rejections need a much longer cool-down. Angel One
                # phrases them two ways: JSON "Too many requests" (AB1021) and
                # a plain-text "exceeding access rate" body.
                msg = message.lower()
                rate_limited = "too many requests" in msg or "access rate" in msg
                time.sleep(10.0 * attempt if rate_limited else 1.5 * attempt)
        log.warning("getCandleData failed for token %s (%s -> %s): %s",
                    token, params["fromdate"], params["todate"], message)
        return []

    def ltp(self, symbol: str) -> float:
        api = self._require_api()
        self._throttle()
        resp = api.ltpData("NSE", f"{symbol}-EQ", self._token(symbol))
        if not resp.get("status"):
            raise RuntimeError(f"ltpData failed for {symbol}: {resp.get('message')}")
        return float(resp["data"]["ltp"])

    def place_order(self, order: Order) -> OrderResult:
        """Intraday (MIS) equity order. Used only after paper trading proves out."""
        api = self._require_api()
        params = {
            "variety": "NORMAL",
            "tradingsymbol": f"{order.symbol}-EQ",
            "symboltoken": self._token(order.symbol),
            "transactiontype": order.side.value,
            "exchange": "NSE",
            "ordertype": "MARKET" if order.price is None else "LIMIT",
            "producttype": "INTRADAY",
            "duration": "DAY",
            "price": order.price or 0,
            "quantity": order.qty,
            "ordertag": order.tag[:20] if order.tag else "",
        }
        resp = api.placeOrderFullResponse(params)
        if not resp.get("status"):
            return OrderResult(order_id="", status="REJECTED",
                               message=resp.get("message", ""))
        return OrderResult(order_id=resp["data"]["orderid"], status="PLACED")
