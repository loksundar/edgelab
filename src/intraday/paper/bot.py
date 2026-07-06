"""Paper-trading bot.

Runs the exact same signal + exit mechanics as the backtester, but forward in
time. Two modes share one code path (`on_bar_close`):

- live: during market hours, wake at every bar close, fetch fresh candles from
  the broker, update positions, evaluate entries. Orders are simulated; P&L is
  net of the same cost model as the backtest.
- replay (dry run): step through the last cached session bar by bar. Used to
  test the bot when the market is closed.
"""

from __future__ import annotations

import logging
import time as time_mod
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta

import pandas as pd

from intraday.backtest.costs import round_trip_cost
from intraday.config import settings
from intraday.data import store
from intraday.paper.journal import Journal, JournalEntry
from intraday.risk.manager import RiskManager
from intraday.signals.registry import Context, all_signals

log = logging.getLogger(__name__)

WINDOW = 450

INTERVAL_MINUTES = {
    "ONE_MINUTE": 1, "THREE_MINUTE": 3, "FIVE_MINUTE": 5,
    "TEN_MINUTE": 10, "FIFTEEN_MINUTE": 15,
}


@dataclass
class Position:
    symbol: str
    signal: str
    side: str
    qty: int
    entry: float
    stop: float
    target: float | None
    entry_time: pd.Timestamp
    reason: str


class PaperBot:
    def __init__(self, symbols: list[str], interval: str, signal_names: list[str],
                 risk: RiskManager, journal: Journal, broker=None):
        import intraday.signals as sig

        sig.load_all()
        self.specs = {n: s for n, s in all_signals().items() if n in signal_names}
        self.symbols = symbols
        self.interval = interval
        self.risk = risk
        self.journal = journal
        self.broker = broker
        self.frames: dict[str, pd.DataFrame] = {}
        self.positions: dict[str, Position] = {}
        self.realized_pnl = 0.0
        self.trades_closed = 0
        h, m = map(int, settings()["market"]["square_off"].split(":"))
        self.square_off_at = dtime(h, m)

    # ── shared core ────────────────────────────────────────────────────────

    def on_bar_close(self, ts: pd.Timestamp) -> None:
        """Process one completed bar timestamp across all symbols."""
        squaring_off = ts.time() >= self.square_off_at
        for symbol in self.symbols:
            frame = self.frames.get(symbol)
            if frame is None or frame.empty or ts not in frame.index:
                continue
            window = frame.loc[:ts].tail(WINDOW)
            bar = window.iloc[-1]
            if symbol in self.positions:
                self._manage_exit(symbol, bar, ts, squaring_off)
            if symbol not in self.positions and not squaring_off:
                self._maybe_enter(symbol, window, ts)

    def _manage_exit(self, symbol: str, bar, ts: pd.Timestamp, squaring_off: bool) -> None:
        pos = self.positions[symbol]
        exit_price = exit_reason = None
        if pos.side == "BUY":
            if bar.low <= pos.stop:
                exit_price, exit_reason = min(pos.stop, bar.open), "stop"
            elif pos.target is not None and bar.high >= pos.target:
                exit_price, exit_reason = max(pos.target, bar.open), "target"
        else:
            if bar.high >= pos.stop:
                exit_price, exit_reason = max(pos.stop, bar.open), "stop"
            elif pos.target is not None and bar.low <= pos.target:
                exit_price, exit_reason = min(pos.target, bar.open), "target"
        if exit_price is None and squaring_off:
            exit_price, exit_reason = float(bar.close), "square_off"
        if exit_price is None:
            return
        direction = 1 if pos.side == "BUY" else -1
        gross = direction * (exit_price - pos.entry) * pos.qty
        net = gross - round_trip_cost(pos.entry * pos.qty, exit_price * pos.qty)
        self.realized_pnl += net
        self.trades_closed += 1
        del self.positions[symbol]
        self.journal.record(JournalEntry(
            entry_time=str(pos.entry_time), exit_time=str(ts), symbol=symbol,
            signal=pos.signal, side=pos.side, qty=pos.qty, entry=pos.entry,
            exit=float(exit_price), stop=pos.stop, target=pos.target,
            exit_reason=exit_reason, net_pnl=round(net, 2), reason=pos.reason,
        ))
        log.info("EXIT  %-12s %s %s qty=%d @ %.2f (%s) pnl=%+.0f | day pnl %+.0f",
                 symbol, pos.signal, pos.side, pos.qty, exit_price, exit_reason,
                 net, self.realized_pnl)

    def _maybe_enter(self, symbol: str, window: pd.DataFrame, ts: pd.Timestamp) -> None:
        ok, why = self.risk.can_enter(len(self.positions), self.realized_pnl)
        if not ok:
            return
        for name, spec in self.specs.items():
            try:
                ev = spec.func(window, Context(symbol=symbol, interval=self.interval,
                                               params=spec.params))
            except Exception:
                log.exception("Signal %s crashed on %s @ %s", name, symbol, ts)
                continue
            if ev is None:
                continue
            qty = self.risk.qty_for(ev.entry, ev.stop)
            if qty <= 0:
                continue
            self.positions[symbol] = Position(
                symbol=symbol, signal=name, side=ev.side, qty=qty,
                entry=ev.entry, stop=ev.stop, target=ev.target,
                entry_time=ts, reason=ev.reason,
            )
            log.info("ENTER %-12s %s %s qty=%d @ %.2f stop=%.2f target=%s (%s)",
                     symbol, name, ev.side, qty, ev.entry, ev.stop,
                     f"{ev.target:.2f}" if ev.target else "-", ev.reason)
            return  # first firing signal wins; one position per symbol

    # ── replay (dry run) ───────────────────────────────────────────────────

    def run_replay(self, day: str | None = None) -> None:
        """Step through one cached session bar by bar (no API needed)."""
        for s in self.symbols:
            self.frames[s] = store.load(s, self.interval)
        all_days = sorted({d for f in self.frames.values() if not f.empty
                           for d in f.index.date})
        if not all_days:
            raise RuntimeError("No cached candles — run `trader download` first")
        target_day = pd.Timestamp(day).date() if day else all_days[-1]
        stamps = sorted({ts for f in self.frames.values()
                         for ts in f.index[f.index.date == target_day]})
        log.info("Replaying %s: %d bar closes, %d symbols, signals: %s",
                 target_day, len(stamps), len(self.symbols), sorted(self.specs))
        for ts in stamps:
            self.on_bar_close(ts)
        self._summary(f"replay {target_day}")

    # ── live loop ──────────────────────────────────────────────────────────

    def run_live(self) -> None:
        if self.broker is None:
            raise RuntimeError("Live mode needs a connected broker")
        minutes = INTERVAL_MINUTES[self.interval]
        log.info("Seeding history for %d symbols...", len(self.symbols))
        now = datetime.now()
        for s in self.symbols:
            cached = store.load(s, self.interval)
            last = cached.index[-1] if not cached.empty else None
            start = (last + timedelta(minutes=1)).to_pydatetime() if last is not None \
                else now - timedelta(days=10)
            if start < now:
                fresh = self.broker.get_candles(s, self.interval, start, now)
                cached = store.upsert(s, self.interval, fresh)
            self.frames[s] = cached

        close_h, close_m = map(int, settings()["market"]["close"].split(":"))
        market_close = dtime(close_h, close_m)
        log.info("Paper bot live: %d symbols, %s, signals: %s",
                 len(self.symbols), self.interval, sorted(self.specs))
        while True:
            now = datetime.now()
            if now.time() >= market_close:
                break
            # sleep to the next bar boundary + a settle delay for the API
            next_bar = (now.replace(second=0, microsecond=0)
                        + timedelta(minutes=minutes - now.minute % minutes))
            wake = next_bar + timedelta(seconds=15)
            time_mod.sleep(max((wake - now).total_seconds(), 1))
            bar_ts = pd.Timestamp(next_bar - timedelta(minutes=minutes))
            for s in self.symbols:
                try:
                    last = self.frames[s].index[-1] if not self.frames[s].empty else None
                    start = (last + timedelta(minutes=1)).to_pydatetime() if last is not None \
                        else datetime.now() - timedelta(days=10)
                    fresh = self.broker.get_candles(s, self.interval, start, datetime.now())
                    if not fresh.empty:
                        self.frames[s] = store.upsert(s, self.interval, fresh)
                except Exception:
                    log.exception("Candle refresh failed for %s", s)
            self.on_bar_close(bar_ts)
        # square off anything left and summarise
        for s in list(self.positions):
            frame = self.frames[s]
            if not frame.empty:
                self._manage_exit(s, frame.iloc[-1], frame.index[-1], squaring_off=True)
        self._summary("live session")

    def _summary(self, label: str) -> None:
        log.info("=== %s done: %d trades closed, %d still open, net P&L %+.0f Rs "
                 "(journal: %s)", label, self.trades_closed, len(self.positions),
                 self.realized_pnl, self.journal.path)
