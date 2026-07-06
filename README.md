# EdgeLab 🔬📉

**An idea-killing machine for Indian market trading strategies.**

EdgeLab is an experimental research lab for NSE intraday & swing trading ideas:
download real market data, drop a strategy in as a single Python function, and
find out — with realistic Indian costs — whether it actually makes money.

Spoiler from our own research: it probably doesn't. **That's the point.** Every
idea EdgeLab kills in simulation is money that stayed in your account.

> ⚠️ **Experimental research project. Not financial advice. Not a trading
> product.** Past simulated performance means nothing about the future. If you
> wire this to a real account, whatever happens next is on you.

## What we learned building it

We threw ~265,000 simulated trades at 12 months of data for ~210 NSE stocks
(5-minute and daily bars), testing 30+ strategy variants from the classic
trading literature — candlestick patterns (Nison), opening range breakouts
(Crabel), RSI(2) (Connors), Bollinger squeezes, CPR/pivots, VWAP plays,
Supertrend, MACD, Donchian/Turtle breakouts, 52-week-high momentum,
cross-sectional momentum, and homegrown mean-reversion ideas.

Findings, net of realistic Indian retail costs (brokerage, STT, exchange
charges, stamp duty, GST, slippage):

| Finding | Detail |
|---|---|
| **Every intraday signal lost money** | 21/21 textbook signals net-negative; best gross edge (+0.04%/trade) was ~5× smaller than round-trip costs (~0.19%) |
| **Costs are the boss** | ₹94 per ₹50k intraday round trip; ~₹200 for delivery. The market prices textbook patterns to ~zero *gross* edge — costs make that a guaranteed loss |
| **Session edges are real** | First-hour and post-14:00 entries were gross-negative across *every* signal; 10:00–13:59 was the only positive window |
| **Dip-buying "stable" stocks fails** | A range-bound stock 1% below its mean is usually a stock that stopped being range-bound. The dip is information |
| **Trend following came closest** | Donchian 55-day breakouts: +0.25% gross per trade, positive 3 of 4 quarters — still ~breakeven after delivery costs |
| **This matches SEBI's numbers** | ~7 in 10 intraday and ~9 in 10 F&O retail traders lose money. Now you can reproduce *why* on your own machine |

## Architecture

```
src/intraday/
├── brokers/        # broker abstraction; Angel One SmartAPI implemented
├── data/           # instrument master, universe, parquet candle store, downloader
├── signals/        # ★ strategy plugins — one @signal function each, auto-discovered
├── backtest/       # event-driven engine, Indian cost models, stats, momentum ranker
├── paper/          # forward paper-trading bot (live or replay), CSV journal
├── risk/           # position sizing, daily loss cap, max positions
└── app.py          # CLI
notebooks/          # Jupyter research playground
```

Adding a strategy is one file:

```python
from intraday.signals.registry import signal, SignalEvent

@signal("my_idea", params={"lookback": 20})
def my_idea(df, ctx):
    """One-line description."""
    last = df.iloc[-1]
    if <your condition>:
        return SignalEvent(side="BUY", entry=last.close,
                           stop=last.close * 0.99, target=last.close * 1.02,
                           reason="why it fired")
    return None
```

It's instantly available to the backtester, the scanner, the notebook helpers,
and the paper bot. No registration, no wiring.

## Quickstart

Requirements: Python 3.10+, a (free) [Angel One SmartAPI](https://smartapi.angelbroking.com)
account for market data.

```bash
pip install -e .

# credentials — create a .ENV file in the repo root (never committed):
# ANGEL_API_KEY=...
# ANGEL_CLIENT_CODE=...
# ANGEL_PIN=...
# ANGEL_TOTP_SECRET=...

trader login-test                 # verify credentials
trader download                   # cache candles (interval/months in config/settings.yaml)
trader signals                    # list registered strategies
trader backtest                   # score everything, net of costs
trader backtest --interval ONE_DAY --signals donchian_breakout_d
trader paper --dry-run            # replay yesterday through the paper bot
trader paper                      # live paper trading during market hours
trader verify-data --repair       # heal gaps from API rate limiting
```

Configuration (universe, costs, risk limits, data paths) lives in
[config/settings.yaml](config/settings.yaml). The candle cache and journals are
written outside the repo (configurable) — keep them off cloud-synced folders.

## Design notes

- **Honest mechanics**: signals fire on a bar's close, fills happen at the
  *next* bar's open; if stop and target collide in one bar the stop wins;
  intraday positions square off at 15:15 IST.
- **Two cost models**: intraday (MIS) and delivery (CNC) with every Indian
  charge itemised — edit them in settings to match your broker.
- **Rate-limit reality**: Angel One's historical API throttles well below its
  documented limits on bulk pulls; the downloader retries with backoff and
  `verify-data` detects and repairs any silent gaps.
- **Research hygiene**: the backtester is deliberately pessimistic. If a
  strategy survives it, *then* paper trade it for months before risking a rupee.

## License

MIT — see [LICENSE](LICENSE).
