"""Trade journal for the paper bot: one CSV per day + running log."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from intraday.config import data_dir

FIELDS = [
    "entry_time", "exit_time", "symbol", "signal", "side", "qty",
    "entry", "exit", "stop", "target", "exit_reason", "net_pnl", "reason",
]


@dataclass
class JournalEntry:
    entry_time: str
    exit_time: str
    symbol: str
    signal: str
    side: str
    qty: int
    entry: float
    exit: float
    stop: float
    target: float | None
    exit_reason: str
    net_pnl: float
    reason: str


class Journal:
    def __init__(self, day: datetime | None = None, tag: str = "paper"):
        d = data_dir() / "paper"
        d.mkdir(parents=True, exist_ok=True)
        stamp = (day or datetime.now()).strftime("%Y%m%d")
        self.path = d / f"{tag}_{stamp}.csv"
        if not self.path.exists():
            with open(self.path, "w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=FIELDS).writeheader()

    def record(self, entry: JournalEntry) -> None:
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writerow(asdict(entry))
