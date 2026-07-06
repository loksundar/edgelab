"""Event-driven backtest engine.

Replays cached candles bar by bar through signal plugins with realistic
mechanics:
- a signal fires on the close of bar t -> entry at the OPEN of bar t+1
- exits: stop hit, target hit, or forced square-off at the configured time
- if stop and target both fall inside one bar, the stop is assumed hit first
  (conservative)
- one open position per (signal, symbol) at a time
- P&L is net of the full Indian intraday cost model on a fixed notional
"""

from __future__ import annotations

import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import time as dtime

import pandas as pd

from intraday.backtest.costs import delivery_round_trip_cost, round_trip_cost
from intraday.config import settings
from intraday.data import store
from intraday.signals.registry import Context, all_signals

log = logging.getLogger(__name__)

WINDOW = 450  # bars of history a signal sees (covers 375-bar means + prev day)

NOTIONAL = 50_000  # rupees committed per trade for research P&L

MAX_HOLD_DAILY_BARS = 15  # time-stop for daily-bar strategies (~3 weeks)


@dataclass
class Trade:
    symbol: str
    signal: str
    side: str
    entry_time: pd.Timestamp
    entry: float
    exit_time: pd.Timestamp
    exit: float
    stop: float
    target: float | None
    exit_reason: str
    reason: str
    cost_mode: str = "intraday"
    gross_pnl: float = field(init=False)
    net_pnl: float = field(init=False)

    def __post_init__(self):
        qty = max(int(NOTIONAL / self.entry), 1)
        direction = 1 if self.side == "BUY" else -1
        cost_fn = delivery_round_trip_cost if self.cost_mode == "delivery" else round_trip_cost
        self.gross_pnl = direction * (self.exit - self.entry) * qty
        self.net_pnl = self.gross_pnl - cost_fn(self.entry * qty, self.exit * qty)


def _square_off_time() -> dtime:
    h, m = map(int, settings()["market"]["square_off"].split(":"))
    return dtime(h, m)


def run_symbol(symbol: str, interval: str, signal_names: list[str],
               days_limit: int | None = None) -> list[Trade]:
    """Backtest all requested signals over one symbol's cached history."""
    import intraday.signals as sig

    sig.load_all()
    specs = {n: s for n, s in all_signals().items() if n in signal_names}
    df = store.load(symbol, interval)
    # Daily files hold ~250 rows/year; signals gate their own lookbacks, so
    # only require enough bars for the shortest daily strategy to warm up.
    min_bars = 120 if interval == "ONE_DAY" else WINDOW
    if df.empty or len(df) < min_bars:
        return []
    if days_limit:
        days = sorted({d for d in df.index.date})[-days_limit:]
        start_ts = pd.Timestamp(days[0])
    else:
        start_ts = df.index[0]

    # Daily bars mean multi-day CNC holds: no square-off, entries fill the
    # next morning, exits add a time-stop, and delivery costs apply.
    is_daily = interval == "ONE_DAY"
    square_off = _square_off_time()
    cost_mode = "delivery" if is_daily else "intraday"
    trades: list[Trade] = []
    # state per signal: None or dict describing the open/pending position
    open_pos: dict[str, dict] = {}
    pending: dict[str, object] = {}  # SignalEvent fired on previous bar close

    index = df.index
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    opens = df["open"].to_numpy()
    closes = df["close"].to_numpy()

    def close_position(name: str, i: int, exit_price: float, exit_reason: str) -> None:
        pos = open_pos.pop(name)
        ev = pos["ev"]
        trades.append(Trade(
            symbol=symbol, signal=name, side=ev.side,
            entry_time=pos["entry_time"], entry=float(pos["entry"]),
            exit_time=index[i], exit=float(exit_price),
            stop=ev.stop, target=ev.target,
            exit_reason=exit_reason, reason=ev.reason, cost_mode=cost_mode,
        ))

    for i in range(len(df)):
        ts = index[i]
        if ts < start_ts:
            continue
        is_square_off = (not is_daily) and ts.time() >= square_off

        # 1) fill pending entries at this bar's open
        for name, ev in list(pending.items()):
            del pending[name]
            if not is_daily and (
                is_square_off or index[i].date() != ev._fire_date  # noqa: SLF001
            ):
                continue  # day ended before entry could happen
            open_pos[name] = {"ev": ev, "entry": opens[i], "entry_time": ts, "bar_i": i}

        # 2) manage open positions
        for name, pos in list(open_pos.items()):
            ev = pos["ev"]
            exit_price = exit_reason = None
            if ev.side == "BUY":
                if lows[i] <= ev.stop:
                    exit_price, exit_reason = min(ev.stop, opens[i]), "stop"
                elif ev.target is not None and highs[i] >= ev.target:
                    exit_price, exit_reason = max(ev.target, opens[i]), "target"
            else:
                if highs[i] >= ev.stop:
                    exit_price, exit_reason = max(ev.stop, opens[i]), "stop"
                elif ev.target is not None and lows[i] <= ev.target:
                    exit_price, exit_reason = min(ev.target, opens[i]), "target"
            if exit_price is None and is_square_off:
                exit_price, exit_reason = closes[i], "square_off"
            if exit_price is None and is_daily:
                hold_limit = ev.max_hold or MAX_HOLD_DAILY_BARS
                if i - pos["bar_i"] >= hold_limit:
                    exit_price, exit_reason = closes[i], "time_stop"
            if exit_price is not None:
                close_position(name, i, exit_price, exit_reason)

        # 3) evaluate signals on this bar's close (only when flat)
        if is_square_off:
            continue
        window = df.iloc[max(0, i + 1 - WINDOW): i + 1]
        for name, spec in specs.items():
            if name in open_pos or name in pending:
                continue
            try:
                ev = spec.func(window, Context(symbol=symbol, interval=interval,
                                               params=spec.params))
            except Exception:
                log.exception("Signal %s crashed on %s @ %s", name, symbol, ts)
                continue
            if ev is not None:
                ev._fire_date = ts.date()  # entry must happen the same day
                pending[name] = ev

    if is_daily and open_pos:
        # Count positions still open when the data ends instead of dropping them.
        last = len(df) - 1
        for name in list(open_pos):
            close_position(name, last, closes[last], "eod_data")
    return trades


def run_backtest(symbols: list[str], interval: str, signal_names: list[str],
                 days_limit: int | None = None, workers: int = 6) -> pd.DataFrame:
    """Run signals over many symbols in parallel; returns a trades DataFrame."""
    all_trades: list[Trade] = []
    if workers <= 1:
        for s in symbols:
            all_trades.extend(run_symbol(s, interval, signal_names, days_limit))
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(run_symbol, s, interval, signal_names, days_limit): s
                for s in symbols
            }
            done = 0
            for fut in as_completed(futures):
                all_trades.extend(fut.result())
                done += 1
                if done % 10 == 0 or done == len(symbols):
                    log.info("Backtested %d/%d symbols", done, len(symbols))
    if not all_trades:
        return pd.DataFrame()
    return pd.DataFrame([vars(t) for t in all_trades])
