"""Cross-sectional momentum portfolio backtest (daily bars).

Classic 6-1 momentum: each month-end, rank the universe by its return over the
prior ~6 months excluding the most recent month (the skip avoids short-term
reversal), buy the top N equal-weight, hold one month. Long-only, CNC.

This is a portfolio-level test, so it lives outside the per-symbol signal
engine. Costs are applied on turnover (delivery: ~0.15% per side + slippage).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from intraday.data import store

LOOKBACK = 63      # ~3 months of sessions (3-1 momentum; fits 12-month data)
SKIP = 21          # skip the most recent month
TOP_N = 20
COST_PER_SIDE = 0.0020   # 0.2% per side: STT 0.1 + txn/stamp + slippage


def load_close_matrix(interval: str = "ONE_DAY") -> pd.DataFrame:
    frames = {}
    for s in store.available_symbols(interval):
        df = store.load(s, interval)
        if not df.empty:
            frames[s] = df["close"]
    wide = pd.DataFrame(frames).sort_index()
    # Drop symbols with too little history to ever rank.
    return wide.dropna(axis=1, thresh=LOOKBACK + SKIP + 21)


def run(top_n: int = TOP_N) -> dict:
    closes = load_close_matrix()
    month_ends = closes.groupby(closes.index.to_period("M")).tail(1).index

    port_rets: list[float] = []
    bench_rets: list[float] = []
    dates: list[pd.Timestamp] = []
    prev_holdings: set[str] = set()

    for i in range(len(month_ends) - 1):
        t0, t1 = month_ends[i], month_ends[i + 1]
        hist = closes.loc[:t0]
        if len(hist) < LOOKBACK + SKIP + 1:
            continue
        past = hist.iloc[-(LOOKBACK + SKIP)]
        recent = hist.iloc[-SKIP - 1]
        momentum = (recent / past - 1).dropna()
        if len(momentum) < top_n * 2:
            continue
        winners = set(momentum.nlargest(top_n).index)

        period = closes.loc[t0:t1]
        fwd = (period.iloc[-1] / period.iloc[0] - 1)
        port_gross = fwd[list(winners)].mean()
        turnover = len(winners - prev_holdings) / top_n     # fraction replaced
        cost = turnover * 2 * COST_PER_SIDE
        port_rets.append(port_gross - cost)
        bench_rets.append(fwd.mean())
        dates.append(t1)
        prev_holdings = winners

    port = pd.Series(port_rets, index=dates, name="momentum")
    bench = pd.Series(bench_rets, index=dates, name="universe_ew")

    def stats(r: pd.Series) -> dict:
        eq = (1 + r).cumprod()
        years = len(r) / 12
        cagr = eq.iloc[-1] ** (1 / years) - 1 if years > 0 else np.nan
        sharpe = r.mean() / r.std() * np.sqrt(12) if r.std() > 0 else np.nan
        dd = (eq / eq.cummax() - 1).min()
        return {"months": len(r), "CAGR%": cagr * 100, "Sharpe": sharpe,
                "MaxDD%": dd * 100, "win_months%": (r > 0).mean() * 100}

    return {
        "portfolio": stats(port),
        "benchmark": stats(bench),
        "monthly": pd.DataFrame({"momentum": port, "universe": bench}),
    }


if __name__ == "__main__":
    res = run()
    print("6-1 momentum, top 20, monthly rebalance, net of turnover costs")
    print("portfolio:", {k: round(v, 2) for k, v in res["portfolio"].items()})
    print("benchmark:", {k: round(v, 2) for k, v in res["benchmark"].items()})
    m = res["monthly"]
    print("\nlast 12 months (%):")
    print((m.tail(12) * 100).round(1).to_string())
