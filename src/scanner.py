"""Main CLI scanner for Polymarket V6."""
import asyncio
import argparse
import logging
from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.panel import Panel
from rich.live import Live

from .database import Database
from .market_fetcher import MarketFetcher
from .research_engine import ResearchEngine
from .analyzer import Analyzer

console = Console()
logger = logging.getLogger(__name__)


class Scanner:
    """Main scanner orchestrator."""
    
    def __init__(self, 
                 db_path: str = "data/markets.db",
                 searxng_url: str = "http://100.112.76.34:8888",
                 ollama_url: str = "http://100.112.76.34:11434",
                 ollama_model: str = "qwen2.5:32b"):
        self.db = Database(db_path)
        self.searxng_url = searxng_url
        self.ollama_url = ollama_url
        self.ollama_model = ollama_model
    
    async def full_scan(self, limit: Optional[int] = None):
        """
        Full scan: fetch all markets, research new/stale, analyze.
        """
        console.print(Panel.fit("[bold blue]🔍 Full Scan Mode[/bold blue]"))
        
        # Phase 1: Fetch markets
        console.print("\n[yellow]Phase 1: Fetching markets...[/yellow]")
        async with MarketFetcher(self.db) as fetcher:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                transient=True,
            ) as progress:
                task = progress.add_task("Fetching from Polymarket API...", total=None)
                markets, new_ids = await fetcher.fetch_all_markets(limit)
                progress.update(task, completed=True)
        
        console.print(f"  ✓ Fetched [green]{len(markets)}[/green] markets")
        console.print(f"  ✓ [cyan]{len(new_ids)}[/cyan] new markets discovered")
        
        # Phase 2: Research
        needs_research = self.db.get_markets(status="active", needs_research=True)
        if limit:
            needs_research = needs_research[:limit]
        
        console.print(f"\n[yellow]Phase 2: Researching {len(needs_research)} markets...[/yellow]")
        
        if needs_research:
            async with ResearchEngine(self.searxng_url) as engine:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                ) as progress:
                    task = progress.add_task("Researching...", total=len(needs_research))
                    
                    # Process in batches for progress updates
                    batch_size = 50
                    for i in range(0, len(needs_research), batch_size):
                        batch = needs_research[i:i+batch_size]
                        await engine.research_markets(batch, self.db)
                        progress.update(task, advance=len(batch))
            
            console.print(f"  ✓ Researched [green]{len(needs_research)}[/green] markets")
        else:
            console.print("  ✓ No markets need research")
        
        # Phase 3: Analyze
        needs_analysis = self.db.get_markets(status="active", needs_analysis=True)
        if limit:
            needs_analysis = needs_analysis[:limit]
        
        console.print(f"\n[yellow]Phase 3: Analyzing {len(needs_analysis)} markets...[/yellow]")
        
        if needs_analysis:
            async with Analyzer(self.ollama_url, self.ollama_model) as analyzer:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                ) as progress:
                    task = progress.add_task("Analyzing with LLM...", total=len(needs_analysis))
                    
                    # Process in batches
                    batch_size = 10
                    all_signals = []
                    for i in range(0, len(needs_analysis), batch_size):
                        batch = needs_analysis[i:i+batch_size]
                        signals = await analyzer.analyze_markets(batch, self.db)
                        all_signals.extend(signals)
                        progress.update(task, advance=len(batch))
            
            buy_signals = [s for s in all_signals if s.signal == "BUY"]
            console.print(f"  ✓ Analyzed [green]{len(needs_analysis)}[/green] markets")
            console.print(f"  ✓ Found [cyan]{len(buy_signals)}[/cyan] BUY signals")
        else:
            console.print("  ✓ No markets need analysis")
        
        # Show opportunities
        await self.show_opportunities()
    
    async def incremental_scan(self, limit: Optional[int] = None):
        """
        Incremental scan: only process truly NEW markets.
        """
        console.print(Panel.fit("[bold green]⚡ Incremental Scan Mode[/bold green]"))
        
        # Fetch and identify new markets
        console.print("\n[yellow]Fetching markets...[/yellow]")
        async with MarketFetcher(self.db) as fetcher:
            _, new_ids = await fetcher.fetch_all_markets(limit)
        
        if not new_ids:
            console.print("[dim]No new markets found.[/dim]")
            return
        
        console.print(f"Found [cyan]{len(new_ids)}[/cyan] new markets")
        
        # Get the new market objects
        new_markets = [self.db.get_market(mid) for mid in new_ids]
        new_markets = [m for m in new_markets if m]
        
        if limit:
            new_markets = new_markets[:limit]
        
        # Research new markets
        console.print(f"\n[yellow]Researching {len(new_markets)} new markets...[/yellow]")
        async with ResearchEngine(self.searxng_url) as engine:
            await engine.research_markets(new_markets, self.db)
        
        # Re-fetch markets with research data
        new_markets = [self.db.get_market(mid) for mid in new_ids[:limit] if limit else new_ids]
        new_markets = [m for m in new_markets if m and m.research_summary]
        
        # Analyze new markets
        console.print(f"\n[yellow]Analyzing {len(new_markets)} markets...[/yellow]")
        async with Analyzer(self.ollama_url, self.ollama_model) as analyzer:
            signals = await analyzer.analyze_markets(new_markets, self.db)
        
        buy_signals = [s for s in signals if s.signal == "BUY"]
        console.print(f"\n✓ Found [cyan]{len(buy_signals)}[/cyan] opportunities in new markets")
        
        # Show new opportunities
        if buy_signals:
            await self.show_opportunities(market_ids=[s.market_id for s in buy_signals])
    
    async def maintenance(self):
        """
        Maintenance mode: update prices, clean resolved markets.
        """
        console.print(Panel.fit("[bold yellow]🔧 Maintenance Mode[/bold yellow]"))
        
        # Run maintenance
        stats = self.db.maintenance()
        
        console.print("\n[bold]Database Statistics:[/bold]")
        console.print(f"  Total markets: {stats['total']}")
        console.print(f"  Active: [green]{stats['active_count']}[/green]")
        console.print(f"  Resolved: [yellow]{stats['resolved_count']}[/yellow]")
        console.print(f"  Closed: [red]{stats.get('closed_count', 0)}[/red]")
        console.print(f"  Purged old resolved: {stats['purged_old_resolved']}")
        console.print(f"  Needs research: {stats['needs_research']}")
        console.print(f"  Needs analysis: {stats['needs_analysis']}")
        
        # Update prices
        console.print("\n[yellow]Updating prices...[/yellow]")
        async with MarketFetcher(self.db) as fetcher:
            updated = await fetcher.update_prices()
        console.print(f"  ✓ Updated {updated} market prices")
        
        # Check for resolved markets
        console.print("\n[yellow]Checking for resolved markets...[/yellow]")
        async with MarketFetcher(self.db) as fetcher:
            resolved = await fetcher.check_resolved()
        console.print(f"  ✓ Marked {len(resolved)} markets as resolved")
    
    async def show_opportunities(self, min_edge: float = 0.05, 
                                  min_confidence: float = 0.6,
                                  market_ids: Optional[list] = None):
        """
        Display trading opportunities.
        """
        console.print(Panel.fit("[bold magenta]💰 Trading Opportunities[/bold magenta]"))
        
        if market_ids:
            opportunities = [self.db.get_market(mid) for mid in market_ids]
            opportunities = [m for m in opportunities if m and m.signal == "BUY"]
        else:
            opportunities = self.db.get_opportunities(min_edge, min_confidence)
        
        if not opportunities:
            console.print("\n[dim]No opportunities found matching criteria.[/dim]")
            console.print(f"[dim](min_edge={min_edge:.0%}, min_confidence={min_confidence:.0%})[/dim]")
            return
        
        # Sort by edge
        opportunities.sort(key=lambda m: m.edge or 0, reverse=True)
        
        # Create table
        table = Table(title=f"Top {len(opportunities)} Opportunities")
        table.add_column("Question", style="cyan", max_width=50)
        table.add_column("Market", justify="center")
        table.add_column("AI Est.", justify="center")
        table.add_column("Edge", justify="center", style="green")
        table.add_column("Conf.", justify="center")
        table.add_column("Size", justify="right", style="yellow")
        table.add_column("Liq.", justify="right")
        
        for m in opportunities[:20]:  # Top 20
            market_price = f"{m.yes_price:.0%}" if m.yes_price else "?"
            ai_prob = f"{m.ai_probability:.0%}" if m.ai_probability else "?"
            edge = f"+{m.edge:.1%}" if m.edge else "?"
            conf = f"{m.ai_confidence:.0%}" if m.ai_confidence else "?"
            size = f"${m.recommended_size:.0f}" if m.recommended_size else "?"
            liq = f"${m.liquidity:,.0f}" if m.liquidity else "?"
            
            # Truncate question
            question = m.question[:47] + "..." if len(m.question) > 50 else m.question
            
            table.add_row(question, market_price, ai_prob, edge, conf, size, liq)
        
        console.print(table)
        
        # Summary
        total_size = sum(m.recommended_size or 0 for m in opportunities)
        avg_edge = sum(m.edge or 0 for m in opportunities) / len(opportunities)
        
        console.print(f"\n[bold]Summary:[/bold]")
        console.print(f"  Total opportunities: {len(opportunities)}")
        console.print(f"  Total recommended capital: ${total_size:,.2f}")
        console.print(f"  Average edge: {avg_edge:.1%}")
    
    async def show_stats(self):
        """Show database statistics."""
        stats = self.db.get_stats()
        
        console.print(Panel.fit("[bold]📊 Database Statistics[/bold]"))
        console.print(f"  Total markets: {stats['total']}")
        console.print(f"  Active: [green]{stats['active']}[/green]")
        console.print(f"  Resolved: [yellow]{stats['resolved']}[/yellow]")
        console.print(f"  With research: {stats['with_research']}")
        console.print(f"  With analysis: {stats['with_analysis']}")
        console.print(f"  BUY signals: [cyan]{stats['buy_signals']}[/cyan]")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Polymarket V6 Scanner")
    parser.add_argument("--full", action="store_true", help="Full scan mode")
    parser.add_argument("--incremental", action="store_true", help="Incremental scan mode")
    parser.add_argument("--maintenance", action="store_true", help="Maintenance mode")
    parser.add_argument("--opportunities", action="store_true", help="Show opportunities")
    parser.add_argument("--stats", action="store_true", help="Show statistics")
    parser.add_argument("--limit", type=int, help="Limit number of markets to process")
    parser.add_argument("--min-edge", type=float, default=0.05, help="Minimum edge for opportunities")
    parser.add_argument("--min-confidence", type=float, default=0.6, help="Minimum confidence")
    parser.add_argument("--db", default="data/markets.db", help="Database path")
    parser.add_argument("--searxng", default="http://100.112.76.34:8888", help="SearXNG URL")
    parser.add_argument("--ollama", default="http://100.112.76.34:11434", help="Ollama URL")
    parser.add_argument("--model", default="qwen2.5:32b", help="Ollama model")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    
    args = parser.parse_args()
    
    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    
    # Create scanner
    scanner = Scanner(
        db_path=args.db,
        searxng_url=args.searxng,
        ollama_url=args.ollama,
        ollama_model=args.model
    )
    
    # Run appropriate mode
    if args.full:
        asyncio.run(scanner.full_scan(args.limit))
    elif args.incremental:
        asyncio.run(scanner.incremental_scan(args.limit))
    elif args.maintenance:
        asyncio.run(scanner.maintenance())
    elif args.opportunities:
        asyncio.run(scanner.show_opportunities(args.min_edge, args.min_confidence))
    elif args.stats:
        asyncio.run(scanner.show_stats())
    else:
        # Default: show stats and opportunities
        asyncio.run(scanner.show_stats())
        asyncio.run(scanner.show_opportunities(args.min_edge, args.min_confidence))


if __name__ == "__main__":
    main()
