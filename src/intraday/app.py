"""CLI entry point: `trader <command>`."""

from __future__ import annotations

import logging

import typer
from rich.console import Console
from rich.table import Table

from intraday.config import settings

app = typer.Typer(help="Intraday signal research and trading app (NSE).")
console = Console()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _connected_broker():
    from intraday.brokers.angelone import AngelOneBroker

    broker = AngelOneBroker()
    broker.connect()
    return broker


@app.command()
def login_test():
    """Verify Angel One credentials by logging in and fetching one LTP."""
    broker = _connected_broker()
    price = broker.ltp("RELIANCE")
    console.print(f"[green]Login OK.[/green] RELIANCE LTP = {price}")


@app.command()
def instruments(refresh: bool = typer.Option(False, help="Force re-download")):
    """Download/refresh the instrument master and show universe stats."""
    from intraday.data import instruments as inst

    master = inst.load_scrip_master(force_refresh=refresh)
    eq = inst.nse_equities(master)
    fno = inst.fno_stock_names(master)
    console.print(f"Instrument master: {len(master):,} instruments")
    console.print(f"NSE cash equities: {len(eq):,}")
    console.print(f"F&O stock universe: {len(fno)} names")


@app.command()
def universe():
    """Show the resolved trading universe from settings.yaml."""
    from intraday.data.universe import resolve_universe

    syms = resolve_universe()
    console.print(f"{len(syms)} symbols: {', '.join(syms)}")


@app.command()
def download(
    interval: str = typer.Option(None, help="Candle interval (default from settings)"),
    months: int = typer.Option(None, help="History depth in months (default from settings)"),
):
    """Download/refresh historical candles for the whole universe."""
    from intraday.data.downloader import download_history
    from intraday.data.universe import resolve_universe

    cfg = settings()["data"]
    interval = interval or cfg["interval"]
    months = months or cfg["history_months"]
    symbols = resolve_universe()
    console.print(f"Downloading {interval} candles, {months} months, {len(symbols)} symbols")

    broker = _connected_broker()
    added = download_history(broker, symbols, interval, months)
    ok = sum(1 for v in added.values() if v >= 0)
    failed = sorted(s for s, v in added.items() if v < 0)
    console.print(f"[green]Done.[/green] {ok}/{len(symbols)} symbols updated, "
                  f"{sum(v for v in added.values() if v > 0):,} candles added.")
    if failed:
        console.print(f"[red]Failed:[/red] {', '.join(failed)}")


@app.command()
def verify_data(
    interval: str = typer.Option(None, help="Candle interval (default from settings)"),
    repair: bool = typer.Option(False, help="Delete gappy symbols so `download` refetches them"),
):
    """Check cached candles for missing trading days (e.g. dropped API chunks).

    A day counts as missing for a symbol if at least half the universe has
    candles for it but the symbol doesn't.
    """
    from intraday.data import store

    interval = interval or settings()["data"]["interval"]
    symbols = store.available_symbols(interval)
    if not symbols:
        console.print("[yellow]No cached data.[/yellow]")
        raise typer.Exit()

    day_sets = {s: {d for d in store.load(s, interval).index.date} for s in symbols}
    from collections import Counter
    day_counts = Counter(d for days in day_sets.values() for d in days)
    common_days = {d for d, n in day_counts.items() if n >= len(symbols) / 2}

    gappy = {}
    for s, days in day_sets.items():
        missing = common_days - days
        # Ignore missing days before the symbol's first candle (later listing
        # or genuinely shorter history) — only holes inside its range count.
        if days:
            missing = {d for d in missing if d > min(days)}
        if missing:
            gappy[s] = sorted(missing)

    console.print(f"{len(symbols)} symbols, {len(common_days)} common trading days")
    if not gappy:
        console.print("[green]No gaps found.[/green]")
        raise typer.Exit()
    for s, missing in sorted(gappy.items()):
        console.print(f"[red]{s}[/red]: {len(missing)} missing days "
                      f"({missing[0]} .. {missing[-1]})")
    if repair:
        from intraday.config import data_dir
        for s in gappy:
            (data_dir() / "candles" / interval / f"{s.replace('&', '_')}.parquet").unlink()
        console.print(f"[yellow]Deleted {len(gappy)} symbols — run `trader download` "
                      f"to refetch them in full.[/yellow]")


@app.command()
def backtest(
    signals: str = typer.Option("all", help="Comma-separated signal names, or 'all'"),
    symbols: str = typer.Option("all", help="Comma-separated symbols, or 'all' cached"),
    interval: str = typer.Option(None, help="Candle interval (default from settings)"),
    days: int = typer.Option(None, help="Limit to the last N trading days"),
    workers: int = typer.Option(6, help="Parallel worker processes"),
):
    """Backtest signals over cached candles; prints ranked per-signal stats."""
    import intraday.signals as sig
    from intraday.backtest.engine import run_backtest
    from intraday.backtest.stats import signal_stats
    from intraday.config import data_dir
    from intraday.data import store
    from intraday.signals.registry import all_signals

    sig.load_all()
    interval = interval or settings()["data"]["interval"]
    sig_names = sorted(all_signals()) if signals == "all" else signals.split(",")
    sym_list = store.available_symbols(interval) if symbols == "all" else symbols.split(",")
    console.print(f"Backtesting {len(sig_names)} signals x {len(sym_list)} symbols "
                  f"({interval}, days={days or 'all'}, workers={workers})")

    trades = run_backtest(sym_list, interval, sig_names, days_limit=days, workers=workers)
    if trades.empty:
        console.print("[yellow]No trades generated.[/yellow]")
        raise typer.Exit()

    out_dir = data_dir() / "backtests"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
    trades_path = out_dir / f"trades_{stamp}.parquet"
    trades.to_parquet(trades_path)

    stats = signal_stats(trades)
    # "Rs" not the rupee sign: Windows consoles often use cp1252, which can't
    # encode U+20B9 and rich crashes on it.
    table = Table("Signal", "Trades", "Win %", "Expectancy Rs", "Total Rs",
                  "PF", "Max DD Rs", title="Net of costs, Rs 50k notional/trade")
    for _, r in stats.iterrows():
        color = "green" if r.expectancy > 0 else "red"
        table.add_row(r.signal, str(r.trades), f"{r.win_rate:.1f}",
                      f"[{color}]{r.expectancy:.0f}[/{color}]",
                      f"{r.total_net_pnl:,.0f}", f"{r.profit_factor:.2f}",
                      f"{r.max_drawdown:,.0f}")
    console.print(table)
    console.print(f"Trades saved to {trades_path}")


@app.command()
def paper(
    dry_run: bool = typer.Option(False, "--dry-run", help="Replay the last cached session instead of trading live"),
    day: str = typer.Option(None, help="Replay a specific date (YYYY-MM-DD), implies --dry-run"),
    symbols: str = typer.Option(None, help="Comma-separated symbols (default: paper.watchlist)"),
    signals: str = typer.Option(None, help="Comma-separated signals (default: paper.signals)"),
):
    """Run the paper-trading bot (simulated orders, real signals + costs)."""
    import intraday.signals as sig
    from intraday.data.universe import resolve_universe
    from intraday.paper.bot import PaperBot
    from intraday.paper.journal import Journal
    from intraday.risk.manager import RiskManager
    from intraday.signals.registry import all_signals

    sig.load_all()
    cfg = settings()
    interval = cfg["data"]["interval"]

    if symbols:
        sym_list = symbols.split(",")
    else:
        watch = cfg["paper"]["watchlist"]
        if watch == "nifty50":
            sym_list = cfg["universe"]["nifty50"]
        else:
            sym_list = resolve_universe()

    sig_cfg = signals.split(",") if signals else cfg["paper"]["signals"]
    sig_names = sorted(all_signals()) if sig_cfg == "all" else list(sig_cfg)

    journal = Journal(tag="dryrun" if (dry_run or day) else "paper")
    bot = PaperBot(sym_list, interval, sig_names, RiskManager.from_settings(), journal)
    if dry_run or day:
        bot.run_replay(day)
    else:
        bot.broker = _connected_broker()
        bot.run_live()


@app.command()
def signals():
    """List all registered signal plugins."""
    import intraday.signals as sig
    from intraday.signals.registry import all_signals

    sig.load_all()
    table = Table("Name", "Description", "Default params")
    for spec in all_signals().values():
        table.add_row(spec.name, spec.description, str(spec.params))
    console.print(table)


def main():
    app()


if __name__ == "__main__":
    main()
