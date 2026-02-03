"""
CLI entry point for Polymarket V6 Alpha Scanner.

Usage:
    python -m src.scanner --full-scan --parallel 50
    python -m src.scanner --phase1 --parallel 50
    python -m src.scanner --phase2 --parallel 200
    python -m src.scanner --results --min-edge 0.10
"""
import argparse
import asyncio
import sys
from datetime import datetime
from typing import Optional
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from .database import Database
from .parallel_scanner import run_phase1
from .deep_researcher import run_phase2

console = Console()

def print_banner():
    """Print startup banner."""
    banner = """
╔══════════════════════════════════════════════════╗
║     🎯 POLYMARKET V6 ALPHA SCANNER 🎯            ║
║     Parallel Two-Phase Market Analysis           ║
╚══════════════════════════════════════════════════╝
    """
    console.print(banner, style="bold cyan")

def print_results(db: Database, min_edge: float = 0.0, 
                 phase: Optional[int] = None,
                 show_buy_only: bool = False,
                 limit: int = 50):
    """Print scan results as a table."""
    
    if show_buy_only:
        results = db.get_alpha_opportunities(min_validated_edge=min_edge)
        title = f"🎯 Alpha Opportunities (validated edge ≥ {min_edge:.0%})"
    else:
        results = db.get_results(min_edge=min_edge, phase=phase, limit=limit)
        title = f"📊 Scan Results (edge ≥ {min_edge:.0%})"
    
    if not results:
        console.print("❌ No results found matching criteria.", style="yellow")
        return
    
    table = Table(title=title, show_lines=True)
    table.add_column("Market ID", style="dim", max_width=12)
    table.add_column("Question", max_width=40)
    table.add_column("Price", justify="right")
    table.add_column("AI Est", justify="right")
    table.add_column("Edge", justify="right")
    table.add_column("Phase", justify="center")
    table.add_column("Decision", justify="center")
    
    for r in results[:limit]:
        edge_style = "green" if r.edge > 0.05 else ("red" if r.edge < -0.05 else "white")
        decision_style = {
            'BUY': 'bold green',
            'SKIP': 'yellow',
            'AVOID': 'red'
        }.get(r.final_decision or '', 'white')
        
        table.add_row(
            r.market_id[:12],
            r.question[:40] + "..." if len(r.question) > 40 else r.question,
            f"{r.market_price:.1%}",
            f"{r.ai_estimate:.1%}",
            f"[{edge_style}]{r.edge:+.1%}[/{edge_style}]",
            str(r.phase),
            f"[{decision_style}]{r.final_decision or '-'}[/{decision_style}]"
        )
    
    console.print(table)
    
    # Print stats
    stats = db.get_stats()
    stats_panel = Panel(
        f"Total Scans: {stats['total_scans']} | "
        f"Phase 1: {stats['phase1_only']} | "
        f"Phase 2: {stats['phase2_complete']} | "
        f"Candidates: {stats['candidates']} | "
        f"BUY Signals: {stats['buy_signals']} | "
        f"Avg Edge: {stats['avg_edge']:.2%}",
        title="📈 Database Stats"
    )
    console.print(stats_panel)

def print_alpha_details(db: Database, min_edge: float = 0.05):
    """Print detailed view of alpha opportunities."""
    results = db.get_alpha_opportunities(min_validated_edge=min_edge)
    
    if not results:
        console.print("❌ No confirmed alpha opportunities.", style="yellow")
        return
    
    console.print(f"\n🎯 [bold green]CONFIRMED ALPHA OPPORTUNITIES ({len(results)} found)[/bold green]\n")
    
    for i, r in enumerate(results, 1):
        panel_content = f"""[bold]Question:[/bold] {r.question}

[bold]Market Price:[/bold] {r.market_price:.1%}
[bold]AI Estimate:[/bold] {r.ai_estimate:.1%}
[bold]Initial Edge:[/bold] {r.edge:+.1%}
[bold]Validated Edge:[/bold] {r.validated_edge:+.1%}

[bold]Initial Reasoning:[/bold]
{r.reasoning}

[bold]Research Summary:[/bold]
{r.research_summary}

[dim]Market ID: {r.market_id}[/dim]
[dim]Scanned: {r.scanned_at} | Researched: {r.researched_at}[/dim]
"""
        console.print(Panel(
            panel_content,
            title=f"#{i} - Validated Edge: {r.validated_edge:+.1%}",
            border_style="green"
        ))
        console.print()

async def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Polymarket V6 Alpha Scanner - Parallel Two-Phase Analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.scanner --full-scan --parallel 50    # Full pipeline
  python -m src.scanner --phase1 --parallel 50       # Phase 1 only
  python -m src.scanner --phase2 --parallel 200      # Phase 2 only
  python -m src.scanner --results --min-edge 0.10    # View results
  python -m src.scanner --alpha                      # View BUY opportunities
  python -m src.scanner --stats                      # Database stats
        """
    )
    
    # Mode selection
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument('--full-scan', action='store_true',
                           help='Run full pipeline (Phase 1 + Phase 2)')
    mode_group.add_argument('--phase1', action='store_true',
                           help='Run Phase 1 parallel scan only')
    mode_group.add_argument('--phase2', action='store_true',
                           help='Run Phase 2 deep research only')
    mode_group.add_argument('--results', action='store_true',
                           help='View scan results')
    mode_group.add_argument('--alpha', action='store_true',
                           help='View confirmed alpha opportunities')
    mode_group.add_argument('--stats', action='store_true',
                           help='Show database statistics')
    mode_group.add_argument('--clear', action='store_true',
                           help='Clear all scan results')
    
    # Options
    parser.add_argument('--parallel', type=int, default=50,
                       help='Number of concurrent operations (default: 50)')
    parser.add_argument('--min-edge', type=float, default=0.05,
                       help='Minimum edge threshold (default: 0.05)')
    parser.add_argument('--limit', type=int, default=None,
                       help='Limit number of markets to scan (for testing)')
    parser.add_argument('--db', type=str, default='data/scans.db',
                       help='Database path (default: data/scans.db)')
    parser.add_argument('--phase', type=int, choices=[1, 2], default=None,
                       help='Filter results by phase')
    
    args = parser.parse_args()
    
    print_banner()
    db = Database(args.db)
    
    if args.full_scan:
        console.print("\n🚀 [bold]Starting Full Pipeline (Phase 1 + Phase 2)[/bold]\n")
        
        # Phase 1
        console.print("[bold cyan]═══ PHASE 1: PARALLEL QUICK SCAN ═══[/bold cyan]")
        stats1 = await run_phase1(
            db_path=args.db,
            max_concurrent=args.parallel,
            market_limit=args.limit
        )
        
        console.print()
        
        # Phase 2
        console.print("[bold magenta]═══ PHASE 2: DEEP RESEARCH ═══[/bold magenta]")
        stats2 = await run_phase2(
            db_path=args.db,
            max_concurrent_searches=min(args.parallel * 4, 200),
            max_concurrent_analysis=min(args.parallel // 2, 20),
            min_edge=args.min_edge
        )
        
        # Final summary
        console.print("\n" + "═" * 50)
        print_alpha_details(db, min_edge=args.min_edge)
        
    elif args.phase1:
        console.print("\n[bold cyan]═══ PHASE 1: PARALLEL QUICK SCAN ═══[/bold cyan]\n")
        await run_phase1(
            db_path=args.db,
            max_concurrent=args.parallel,
            market_limit=args.limit
        )
        
    elif args.phase2:
        console.print("\n[bold magenta]═══ PHASE 2: DEEP RESEARCH ═══[/bold magenta]\n")
        await run_phase2(
            db_path=args.db,
            max_concurrent_searches=min(args.parallel, 200),
            max_concurrent_analysis=min(args.parallel // 10, 20),
            min_edge=args.min_edge
        )
        
    elif args.results:
        print_results(db, min_edge=args.min_edge, phase=args.phase, limit=50)
        
    elif args.alpha:
        print_alpha_details(db, min_edge=args.min_edge)
        
    elif args.stats:
        stats = db.get_stats()
        table = Table(title="📊 Database Statistics")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")
        
        for key, value in stats.items():
            if isinstance(value, float):
                table.add_row(key.replace('_', ' ').title(), f"{value:.2%}" if 'edge' in key else f"{value:.1f}")
            else:
                table.add_row(key.replace('_', ' ').title(), str(value))
        
        console.print(table)
        
    elif args.clear:
        confirm = input("⚠️  Are you sure you want to clear all scan results? (yes/no): ")
        if confirm.lower() == 'yes':
            db.clear_all()
            console.print("✅ Database cleared.", style="green")
        else:
            console.print("❌ Cancelled.", style="yellow")

def cli():
    """CLI wrapper for entry point."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n⚠️  Interrupted by user.", style="yellow")
        sys.exit(1)

if __name__ == "__main__":
    cli()
