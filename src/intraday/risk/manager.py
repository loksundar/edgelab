"""Position sizing and account-level risk limits for the trading bot."""

from __future__ import annotations

from dataclasses import dataclass

from intraday.config import settings


@dataclass
class RiskManager:
    capital: float
    risk_per_trade_pct: float
    daily_loss_cap_pct: float
    max_open_positions: int

    @classmethod
    def from_settings(cls) -> "RiskManager":
        r = settings()["risk"]
        return cls(
            capital=r["capital"],
            risk_per_trade_pct=r["risk_per_trade_pct"],
            daily_loss_cap_pct=r["daily_loss_cap_pct"],
            max_open_positions=r["max_open_positions"],
        )

    def qty_for(self, entry: float, stop: float) -> int:
        """Shares such that hitting the stop loses ~risk_per_trade_pct of
        capital, capped so one position never hogs the whole account."""
        per_share_risk = abs(entry - stop)
        if per_share_risk <= 0 or entry <= 0:
            return 0
        risk_qty = (self.capital * self.risk_per_trade_pct / 100) / per_share_risk
        notional_qty = (self.capital / self.max_open_positions) / entry
        return int(min(risk_qty, notional_qty))

    def can_enter(self, open_positions: int, realized_pnl_today: float) -> tuple[bool, str]:
        if open_positions >= self.max_open_positions:
            return False, f"max open positions ({self.max_open_positions}) reached"
        if realized_pnl_today <= -self.capital * self.daily_loss_cap_pct / 100:
            return False, f"daily loss cap ({self.daily_loss_cap_pct}%) hit"
        return True, ""
