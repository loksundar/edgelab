"""Per-signal performance statistics over a trades DataFrame."""

from __future__ import annotations

import numpy as np
import pandas as pd


def signal_stats(trades: pd.DataFrame) -> pd.DataFrame:
    """One row per signal, ranked by expectancy. Columns are self-describing;
    'expectancy' is mean net P&L per trade in rupees on the fixed notional."""
    if trades.empty:
        return pd.DataFrame()
    rows = []
    for name, g in trades.groupby("signal"):
        pnl = g["net_pnl"]
        wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
        gross_win, gross_loss = wins.sum(), -losses.sum()
        equity = pnl.cumsum()
        drawdown = (equity - equity.cummax()).min()
        rows.append({
            "signal": name,
            "trades": len(g),
            "win_rate": len(wins) / len(g) * 100,
            "expectancy": pnl.mean(),
            "total_net_pnl": pnl.sum(),
            "profit_factor": gross_win / gross_loss if gross_loss > 0 else np.inf,
            "avg_win": wins.mean() if len(wins) else 0.0,
            "avg_loss": losses.mean() if len(losses) else 0.0,
            "max_drawdown": drawdown,
            "stop_exits_pct": (g["exit_reason"] == "stop").mean() * 100,
            "target_exits_pct": (g["exit_reason"] == "target").mean() * 100,
        })
    out = pd.DataFrame(rows).sort_values("expectancy", ascending=False)
    return out.reset_index(drop=True)
