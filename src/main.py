"""Polymarket AI Trader - Main CLI Entry Point.

Usage:
    python -m src.main scan              # Scan markets and show opportunities
    python -m src.main analyze <id>      # Deep-analyze a specific market
    python -m src.main trade             # Run full scan → signal → paper trade pipeline
    python -m src.main portfolio         # Show portfolio status
    python -m src.main history           # Show trade history
    python -m src.main init              # Initialize database and portfolio
"""

from __future__ import annotations

import asyncio
import sys
import structlog
from datetime import datetime, timezone
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from src.core.config import config
from src.core import database as db
from src.market.client import fetch_active_markets, categorize_market
from src.analysis.ai_analyzer import quick_scan, deep_analysis
from src.news.collector import search_news_for_market
from src.strategy.signals import generate_signal, check_risk, rank_signals
from src.execution.paper_trader import execute_paper_trade, update_positions_pnl

structlog.configure(
    processors=[
        structlog.dev.ConsoleRenderer(colors=True),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO level
)

console = Console()
log = structlog.get_logger()


async def cmd_init():
    """Initialize the database and portfolio."""
    bankroll = config.trading.initial_bankroll
    await db.init_portfolio(bankroll)
    console.print(f"[green]Portfolio initialized with ${bankroll:.2f}[/green]")
    console.print(f"[dim]Database: {config.db_path}[/dim]")


async def cmd_scan(top_n: int = 20):
    """Scan markets, run quick AI analysis, show opportunities."""
    console.print(Panel("[bold cyan]Scanning Polymarket for opportunities...[/bold cyan]"))

    # Fetch markets
    markets = await fetch_active_markets(limit=100, min_volume=100)
    if not markets:
        console.print("[red]No markets found. Check your internet connection.[/red]")
        return

    # Categorize
    for m in markets:
        if not m.get("category"):
            m["category"] = categorize_market(m["question"], m.get("description", ""))

    console.print(f"Found [bold]{len(markets)}[/bold] active markets. Analyzing top {top_n}...")

    # Quick scan top markets
    results = []
    for m in markets[:top_n]:
        try:
            # Collect news
            news = await search_news_for_market(m)

            # Quick AI analysis
            analysis = await quick_scan(m, news=news)

            # Save to DB
            await db.save_market(m)
            await db.save_analysis(analysis)

            # Generate signal
            signal = generate_signal(analysis, m)
            results.append((m, analysis, signal))

        except Exception as e:
            log.warning("scan_error", market=m["question"][:50], error=str(e))
            continue

    # Display results
    _display_scan_results(results)
    return results


async def cmd_analyze(condition_id: str):
    """Deep-analyze a specific market."""
    console.print(Panel(f"[bold cyan]Deep Analysis: {condition_id[:20]}...[/bold cyan]"))

    # Find market
    markets = await fetch_active_markets(limit=200)
    market = next((m for m in markets if m["condition_id"] == condition_id), None)

    if not market:
        console.print(f"[red]Market not found: {condition_id}[/red]")
        return

    # Collect news
    news = await search_news_for_market(market)
    console.print(f"Found [bold]{len(news)}[/bold] relevant news articles")

    # Deep analysis with Sonnet
    analysis = await deep_analysis(market, news=news)

    await db.save_market(market)
    await db.save_analysis(analysis)

    _display_deep_analysis(market, analysis)
    return analysis


async def cmd_trade(dry_run: bool = True):
    """Full pipeline: scan → analyze → generate signals → execute paper trades."""
    console.print(Panel("[bold yellow]Trading Pipeline[/bold yellow]"))

    # Ensure portfolio exists
    portfolio = await db.get_portfolio()
    if not portfolio:
        await cmd_init()
        portfolio = await db.get_portfolio()

    console.print(f"Cash: [green]${portfolio['cash']:.2f}[/green] | P&L: ${portfolio['total_pnl']:.2f}")

    # Scan markets
    results = await cmd_scan(top_n=15)
    if not results:
        return

    # Collect signals
    signals = [sig for _, _, sig in results if sig is not None]
    if not signals:
        console.print("[yellow]No trading signals generated. No edge found.[/yellow]")
        return

    # Rank signals
    ranked = rank_signals(signals)
    console.print(f"\n[bold]Top {len(ranked)} signals:[/bold]")

    for i, sig in enumerate(ranked[:5], 1):
        color = "green" if sig.strength == "HIGH" else "yellow" if sig.strength == "MEDIUM" else "white"
        console.print(
            f"  {i}. [{color}]{sig.side}[/{color}] {sig.question[:60]}\n"
            f"     Edge: {sig.edge:.1%} | Size: ${sig.suggested_size_usd:.2f} | "
            f"Strength: {sig.strength}"
        )

    if dry_run:
        console.print("\n[dim]Dry run mode. Use 'trade --execute' to paper trade.[/dim]")
        return ranked

    # Execute paper trades for top signals
    executed = []
    for sig in ranked[:config.trading.max_daily_trades]:
        approved, reason = await check_risk(sig)
        if approved:
            trade = await execute_paper_trade(sig)
            executed.append(trade)
            console.print(f"  [green]PAPER TRADE[/green] {sig.side} {sig.question[:50]} @ ${sig.market_price:.3f}")
        else:
            console.print(f"  [red]BLOCKED[/red] {sig.question[:50]}: {reason}")

    console.print(f"\n[bold]Executed {len(executed)} paper trades[/bold]")
    return executed


async def cmd_portfolio():
    """Display current portfolio status."""
    portfolio = await db.get_portfolio()
    if not portfolio:
        console.print("[red]Portfolio not initialized. Run 'init' first.[/red]")
        return

    # Update P&L
    positions = await update_positions_pnl()
    portfolio = await db.get_portfolio()

    # Portfolio summary
    table = Table(title="Portfolio Summary", show_header=False, padding=(0, 2))
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    bankroll = portfolio["bankroll"]
    cash = portfolio["cash"]
    pnl = portfolio["total_pnl"]
    invested = bankroll - cash
    total_value = cash + invested + pnl

    table.add_row("Initial Bankroll", f"${bankroll:.2f}")
    table.add_row("Cash Available", f"${cash:.2f}")
    table.add_row("Invested", f"${invested:.2f}")
    table.add_row("Unrealized P&L", f"[{'green' if pnl >= 0 else 'red'}]${pnl:+.2f}[/]")
    table.add_row("Total Value", f"[bold]${total_value:.2f}[/bold]")
    table.add_row("Return", f"[{'green' if pnl >= 0 else 'red'}]{pnl/bankroll:+.1%}[/]")
    table.add_row("Trades Today", str(portfolio["trades_today"]))

    console.print(table)

    # Open positions
    if positions:
        pos_table = Table(title="\nOpen Positions")
        pos_table.add_column("Market", max_width=50)
        pos_table.add_column("Side")
        pos_table.add_column("Shares", justify="right")
        pos_table.add_column("Avg Price", justify="right")
        pos_table.add_column("Current", justify="right")
        pos_table.add_column("P&L", justify="right")

        for p in positions:
            pnl_val = p.get("unrealized_pnl", 0)
            pnl_color = "green" if pnl_val >= 0 else "red"
            pos_table.add_row(
                p.get("question", p["condition_id"])[:50],
                p["side"],
                f"{p['shares']:.2f}",
                f"${p['avg_price']:.3f}",
                f"${p.get('current_price', 0):.3f}",
                f"[{pnl_color}]${pnl_val:+.4f}[/]",
            )
        console.print(pos_table)
    else:
        console.print("\n[dim]No open positions[/dim]")


async def cmd_history(limit: int = 20):
    """Display trade history."""
    trades = await db.get_trade_history(limit=limit)
    if not trades:
        console.print("[dim]No trade history yet[/dim]")
        return

    table = Table(title="Trade History")
    table.add_column("Time", style="dim")
    table.add_column("Market", max_width=40)
    table.add_column("Side")
    table.add_column("Price", justify="right")
    table.add_column("Size", justify="right")
    table.add_column("Edge", justify="right")
    table.add_column("Status")

    for t in trades:
        side_color = "green" if "YES" in t["side"] else "red"
        table.add_row(
            t["timestamp"][:16],
            t.get("question", t["condition_id"])[:40],
            f"[{side_color}]{t['side']}[/]",
            f"${t['price']:.3f}",
            f"${t['size_usd']:.2f}",
            f"{t.get('edge', 0):.1%}" if t.get("edge") else "-",
            t["status"],
        )

    console.print(table)


def _display_scan_results(results: list):
    """Display scan results in a rich table."""
    table = Table(title="Market Scan Results")
    table.add_column("#", style="dim", width=3)
    table.add_column("Market", max_width=50)
    table.add_column("Cat", width=8)
    table.add_column("YES $", justify="right", width=7)
    table.add_column("AI Prob", justify="right", width=7)
    table.add_column("Edge", justify="right", width=7)
    table.add_column("Signal", width=10)
    table.add_column("Size", justify="right", width=7)

    for i, (market, analysis, signal) in enumerate(results, 1):
        edge = analysis["edge"]
        edge_color = "green" if abs(edge) >= 0.08 else "yellow" if abs(edge) >= 0.05 else "dim"

        signal_text = "-"
        size_text = "-"
        if signal:
            sig_color = "green" if signal.strength == "HIGH" else "yellow"
            signal_text = f"[{sig_color}]{signal.side}[/]"
            size_text = f"${signal.suggested_size_usd:.2f}"

        table.add_row(
            str(i),
            market["question"][:50],
            market.get("category", "?")[:8],
            f"${market.get('yes_price', 0):.3f}",
            f"{analysis['ai_probability']:.0%}",
            f"[{edge_color}]{edge:+.1%}[/]",
            signal_text,
            size_text,
        )

    console.print(table)


def _display_deep_analysis(market: dict, analysis: dict):
    """Display deep analysis results."""
    console.print(f"\n[bold]{market['question']}[/bold]")
    console.print(f"Category: {market.get('category', '?')} | Volume: ${market.get('volume_24h', 0):,.0f}")
    console.print(f"Closes: {market.get('end_date', 'unknown')}\n")

    # Prices
    yes_price = market.get("yes_price", 0)
    ai_prob = analysis["ai_probability"]
    edge = analysis["edge"]

    table = Table(show_header=False, padding=(0, 2))
    table.add_column("", style="bold")
    table.add_column("", justify="right")
    table.add_row("Market YES Price", f"${yes_price:.3f} ({yes_price:.0%})")
    table.add_row("AI Probability", f"{ai_prob:.1%}")
    table.add_row("Edge", f"[{'green' if abs(edge) >= 0.08 else 'yellow'}]{edge:+.1%}[/]")
    table.add_row("Confidence", f"{analysis['confidence']}/10")
    table.add_row("Recommendation", f"[bold]{analysis['recommendation']}[/bold]")
    console.print(table)

    # Arguments
    if analysis.get("arguments_yes"):
        console.print("\n[green]Arguments for YES:[/green]")
        for arg in analysis["arguments_yes"]:
            console.print(f"  + {arg}")

    if analysis.get("arguments_no"):
        console.print("\n[red]Arguments for NO:[/red]")
        for arg in analysis["arguments_no"]:
            console.print(f"  - {arg}")

    if analysis.get("market_blind_spots"):
        console.print("\n[yellow]Market blind spots:[/yellow]")
        for spot in analysis["market_blind_spots"]:
            console.print(f"  ! {spot}")

    console.print(f"\n[dim]Reasoning: {analysis.get('reasoning', 'N/A')}[/dim]")


async def async_main():
    args = sys.argv[1:]
    if not args:
        console.print(Panel(
            "[bold]Polymarket AI Trader[/bold]\n\n"
            "Commands:\n"
            "  [cyan]init[/cyan]              Initialize portfolio ($50)\n"
            "  [cyan]scan[/cyan]              Scan markets for opportunities\n"
            "  [cyan]analyze <id>[/cyan]      Deep-analyze a specific market\n"
            "  [cyan]trade[/cyan]             Scan + generate signals (dry run)\n"
            "  [cyan]trade --execute[/cyan]   Scan + paper trade best signals\n"
            "  [cyan]portfolio[/cyan]         Show portfolio status\n"
            "  [cyan]history[/cyan]           Show trade history\n",
            title="Usage: python -m src.main <command>",
        ))
        return

    cmd = args[0].lower()

    if cmd == "init":
        await cmd_init()
    elif cmd == "scan":
        n = int(args[1]) if len(args) > 1 else 20
        await cmd_scan(top_n=n)
    elif cmd == "analyze":
        if len(args) < 2:
            console.print("[red]Usage: analyze <condition_id>[/red]")
            return
        await cmd_analyze(args[1])
    elif cmd == "trade":
        execute = "--execute" in args
        await cmd_trade(dry_run=not execute)
    elif cmd == "portfolio":
        await cmd_portfolio()
    elif cmd == "history":
        await cmd_history()
    else:
        console.print(f"[red]Unknown command: {cmd}[/red]")


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
