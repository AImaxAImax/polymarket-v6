"""
V6 Alpha Hunter — Main Orchestrator

The brain of the trading bot. Connects all components:
- Alpha Scanner: Find mispriced markets
- Deep Research: Validate with web research
- Conviction Engine: Score and filter
- Position Manager: Execute and manage trades
- Learning Loop: Track outcomes and improve

Usage:
    python -m src.bot scan              # Scan and show opportunities
    python -m src.bot run --paper       # Paper trading mode
    python -m src.bot run --live --confirm  # Live trading (real money)
    python -m src.bot status            # Show positions
    python -m src.bot report            # Learning report
"""

import asyncio
import argparse
import json
import logging
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from .bot_config import BotConfig, bot_config, get_paper_config, get_live_config, get_scan_only_config
from .alpha_scanner import AlphaScanner
from .deep_research import DeepResearcher
from .conviction_engine import ConvictionEngine
from .position_manager import PositionManager
from .risk_manager import RiskManager, RiskConfig
from .learning_loop import LearningLoop, TradeOutcome
from .models import (
    AlphaOpportunity, ConvictionScore, Position, PositionStatus,
    Direction, ResearchResult
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("v6.bot")


class AlphaHunterBot:
    """
    Main orchestrator for the V6 Alpha Hunter trading bot.
    
    Coordinates all components to:
    1. Scan all markets for alpha
    2. Research top opportunities
    3. Score conviction
    4. Execute approved trades
    5. Manage positions (scale-in, TP, SL)
    6. Learn from outcomes
    """
    
    def __init__(self, config: BotConfig = bot_config):
        self.config = config
        self.config.ensure_data_dir()
        
        # Initialize components
        self.scanner: Optional[AlphaScanner] = None
        self.researcher: Optional[DeepResearcher] = None
        self.conviction_engine = ConvictionEngine()
        self.position_manager = PositionManager(
            db_path=str(self.config.positions_db_path),
            risk_config=RiskConfig(
                max_concurrent_positions=self.config.max_concurrent_positions,
                max_total_exposure_pct=self.config.max_exposure_pct,
            ),
            initial_bankroll=self.config.initial_capital,
        )
        self.learning_loop = LearningLoop(
            db_path=self.config.learning_db_path,
        )
        
        # State
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._last_scan_time: Optional[datetime] = None
        
        # Stats
        self.stats = {
            "scans_completed": 0,
            "opportunities_found": 0,
            "trades_executed": 0,
            "total_pnl": 0.0,
        }
        
        logger.info(f"🚀 V6 Alpha Hunter initialized")
        logger.info(f"   Mode: {'📄 PAPER' if self.config.paper_trading else '💰 LIVE'}")
        logger.info(f"   Capital: ${self.config.initial_capital:,.2f}")
        logger.info(f"   Data dir: {self.config.data_dir}")
    
    # === Lifecycle ===
    
    async def start(self):
        """Start the bot and all async components."""
        self.scanner = AlphaScanner()
        self.researcher = DeepResearcher()
        
        await self.scanner.__aenter__()
        await self.researcher.__aenter__()
        
        self._running = True
        logger.info("✅ Bot started")
    
    async def stop(self):
        """Stop the bot and cleanup."""
        self._running = False
        self._shutdown_event.set()
        
        if self.scanner:
            await self.scanner.__aexit__(None, None, None)
        if self.researcher:
            await self.researcher.__aexit__(None, None, None)
        
        logger.info("🛑 Bot stopped")
    
    async def __aenter__(self):
        await self.start()
        return self
    
    async def __aexit__(self, *args):
        await self.stop()
    
    # === Full Scan Flow ===
    
    async def run_full_scan(self) -> list[ConvictionScore]:
        """
        Execute complete scan pipeline:
        1. Scan ALL markets
        2. Filter to 20%+ edge
        3. Deep research top 50
        4. Score conviction
        5. Filter to 8+ approved
        
        Returns list of approved opportunities sorted by conviction.
        """
        logger.info("=" * 60)
        logger.info("🔍 STARTING FULL MARKET SCAN")
        logger.info("=" * 60)
        
        # Step 1: Scan ALL markets
        logger.info(f"Step 1: Scanning markets (limit: {self.config.max_markets_per_scan or 'ALL'})")
        scan_result = await self.scanner.scan(max_markets=self.config.max_markets_per_scan)
        
        logger.info(f"   Scanned {scan_result.total_markets_scanned} markets in {scan_result.scan_duration_sec:.1f}s")
        logger.info(f"   Found {scan_result.markets_with_alpha} with 20%+ edge")
        
        if not scan_result.opportunities:
            logger.info("   No alpha opportunities found!")
            return []
        
        # Step 2: Filter to minimum edge
        alpha_opportunities = [
            o for o in scan_result.opportunities 
            if o.edge_pct >= self.config.min_edge_pct
        ]
        alpha_opportunities.sort(key=lambda x: x.edge_pct, reverse=True)
        
        logger.info(f"   {len(alpha_opportunities)} opportunities with {self.config.min_edge_pct}%+ edge")
        
        if not alpha_opportunities:
            return []
        
        # Step 3: Deep research top N
        top_count = min(len(alpha_opportunities), self.config.top_opportunities_to_research)
        top_opportunities = alpha_opportunities[:top_count]
        
        logger.info(f"\nStep 2: Deep researching top {top_count} opportunities...")
        researched = await self.researcher.research_batch(top_opportunities)
        
        logger.info(f"   Researched {len(researched)} opportunities")
        
        # Step 4: Score conviction
        logger.info(f"\nStep 3: Scoring conviction...")
        scored = self.conviction_engine.score_batch(researched)
        
        # Step 5: Filter to approved
        approved = [s for s in scored if s.trade_approved]
        
        logger.info(f"   {len(approved)}/{len(scored)} opportunities approved (conviction ≥ {self.config.min_conviction_score})")
        
        # Update stats
        self.stats["scans_completed"] += 1
        self.stats["opportunities_found"] += len(approved)
        self._last_scan_time = datetime.utcnow()
        
        # Log top opportunities
        if approved:
            logger.info("\n" + "=" * 60)
            logger.info("🎯 APPROVED OPPORTUNITIES")
            logger.info("=" * 60)
            for i, score in enumerate(approved[:10], 1):
                opp = score.research_result.opportunity
                logger.info(
                    f"{i}. [{score.score:.1f}/10] {opp.direction.value} @ {opp.market_price:.1%} "
                    f"(edge: {score.research_result.edge_pct_post:.1f}%)"
                )
                logger.info(f"   {opp.question[:70]}...")
        
        return approved
    
    # === Trading ===
    
    async def execute_trades(self, approved: list[ConvictionScore]) -> list[Position]:
        """
        Execute trades for approved opportunities.
        
        Respects:
        - Max new positions per cycle
        - Portfolio exposure limits
        - Paper vs live mode
        """
        if not approved:
            return []
        
        if self.config.max_new_positions_per_cycle == 0:
            logger.info("Trading disabled (max_new_positions_per_cycle=0)")
            return []
        
        portfolio = self.position_manager.get_portfolio_state()
        
        # Check if we can open new positions
        if portfolio.position_count >= self.config.max_concurrent_positions:
            logger.info(f"Max positions ({self.config.max_concurrent_positions}) reached")
            return []
        
        mode = "PAPER" if self.config.paper_trading else "LIVE"
        logger.info(f"\n📈 EXECUTING TRADES ({mode} mode)")
        
        positions_opened = []
        max_new = self.config.max_new_positions_per_cycle
        remaining_slots = self.config.max_concurrent_positions - portfolio.position_count
        to_trade = min(max_new, remaining_slots, len(approved))
        
        for score in approved[:to_trade]:
            opp = score.research_result.opportunity
            
            # Check if already have position in this market
            existing = self.position_manager.get_position_by_market(opp.market_id)
            if existing:
                logger.info(f"   ⏭️ Skip {opp.market_id} - already have position")
                continue
            
            # Calculate position size
            position_size = portfolio.total_bankroll * score.recommended_position_pct
            
            # Execute trade (paper or live)
            if self.config.paper_trading:
                position, msg = self._execute_paper_trade(opp, position_size, score)
            else:
                position, msg = await self._execute_live_trade(opp, position_size, score)
            
            if position:
                positions_opened.append(position)
                logger.info(f"   {msg}")
                self.stats["trades_executed"] += 1
            else:
                logger.warning(f"   ⚠️ Failed: {msg}")
        
        return positions_opened
    
    def _execute_paper_trade(
        self, 
        opp: AlphaOpportunity, 
        size: float, 
        score: ConvictionScore
    ) -> tuple[Optional[Position], str]:
        """Execute paper trade (simulated)."""
        position, msg = self.position_manager.open_position(
            opportunity=opp,
            target_size_usd=size,
            entry_price=opp.market_price,
            is_high_conviction=score.score >= 9.5,
        )
        return position, f"📄 PAPER: {msg}"
    
    async def _execute_live_trade(
        self, 
        opp: AlphaOpportunity, 
        size: float, 
        score: ConvictionScore
    ) -> tuple[Optional[Position], str]:
        """Execute live trade (real money)."""
        # TODO: Integrate with Polymarket API for real execution
        # For now, just log that this would be a real trade
        logger.warning(f"💰 LIVE TRADE would execute: {opp.direction.value} ${size:.2f} on {opp.market_id}")
        
        # Still record in position manager for tracking
        position, msg = self.position_manager.open_position(
            opportunity=opp,
            target_size_usd=size,
            entry_price=opp.market_price,
            is_high_conviction=score.score >= 9.5,
        )
        return position, f"💰 LIVE: {msg}"
    
    # === Position Management ===
    
    async def check_positions(self) -> list[str]:
        """
        Check all positions for exits (TP/SL).
        Returns list of actions taken.
        """
        actions = []
        positions = self.position_manager.get_active_positions()
        
        if not positions:
            return actions
        
        logger.info(f"Checking {len(positions)} active positions...")
        
        for position in positions:
            # Get current price (in paper mode, use last known)
            # TODO: Fetch real prices from Polymarket API
            current_price = position.current_price  # Placeholder
            
            # Check stop loss
            position, msg = self.position_manager.stop_loss(position, current_price)
            if "🛑" in msg:
                actions.append(msg)
                await self._record_closed_position(position)
                continue
            
            # Check take profit
            position, msg = self.position_manager.take_profit(position, current_price)
            if "💰" in msg:
                actions.append(msg)
        
        return actions
    
    async def _record_closed_position(self, position: Position):
        """Record a closed position in the learning loop."""
        # Determine if it was a win
        is_win = position.realized_pnl > 0
        pnl_pct = (position.realized_pnl / position.target_size_usd) * 100 if position.target_size_usd > 0 else 0
        
        outcome = TradeOutcome(
            market_id=position.market_id,
            question=position.question,
            category="uncategorized",  # Would need to track this
            direction=position.direction.value,
            entry_price=position.avg_entry_price,
            exit_price=position.current_price,
            ai_estimate=position.avg_entry_price,  # Placeholder
            conviction_score=8.0,  # Would need to track
            edge_at_entry=0,  # Would need to track
            resolved_outcome=position.direction.value if is_win else ("NO" if position.direction == Direction.YES else "YES"),
            is_win=is_win,
            pnl=pnl_pct,
            entry_timestamp=position.created_at,
            exit_timestamp=position.closed_at or datetime.utcnow(),
        )
        
        self.learning_loop.record_trade(outcome)
        self.stats["total_pnl"] += position.realized_pnl
    
    # === Main Trading Loop ===
    
    async def trading_loop(self):
        """
        Main trading loop:
        1. Check existing positions for exits
        2. Run full scan if under max positions
        3. Execute approved trades
        4. Record outcomes
        5. Sleep until next cycle
        """
        logger.info("🔄 Starting trading loop")
        
        while self._running and not self._shutdown_event.is_set():
            try:
                # Check positions for TP/SL
                actions = await self.check_positions()
                for action in actions:
                    logger.info(f"Position action: {action}")
                
                # Check if we can open new positions
                portfolio = self.position_manager.get_portfolio_state()
                can_open = portfolio.position_count < self.config.max_concurrent_positions
                
                if can_open:
                    # Run full scan
                    approved = await self.run_full_scan()
                    
                    # Execute trades
                    if approved:
                        await self.execute_trades(approved)
                else:
                    logger.info(f"At max positions ({portfolio.position_count}), skipping scan")
                
                # Sleep until next cycle
                sleep_seconds = self.config.scan_interval_hours * 3600
                logger.info(f"💤 Sleeping for {self.config.scan_interval_hours}h until next scan...")
                
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=sleep_seconds
                    )
                except asyncio.TimeoutError:
                    pass  # Normal timeout, continue loop
                    
            except Exception as e:
                logger.exception(f"Error in trading loop: {e}")
                await asyncio.sleep(60)  # Wait before retry
        
        logger.info("Trading loop ended")
    
    # === Status & Reporting ===
    
    def get_status(self) -> dict:
        """Get current bot status."""
        portfolio = self.position_manager.get_portfolio_state()
        positions = self.position_manager.get_active_positions()
        
        return {
            "mode": "PAPER" if self.config.paper_trading else "LIVE",
            "running": self._running,
            "last_scan": self._last_scan_time.isoformat() if self._last_scan_time else None,
            "stats": self.stats,
            "portfolio": {
                "total_bankroll": portfolio.total_bankroll,
                "cash_available": portfolio.cash_available,
                "total_exposure": portfolio.total_exposure,
                "exposure_pct": portfolio.exposure_pct,
                "unrealized_pnl": portfolio.unrealized_pnl,
                "realized_pnl": portfolio.realized_pnl,
            },
            "positions": [
                {
                    "market_id": p.market_id,
                    "question": p.question[:60] + "...",
                    "direction": p.direction.value,
                    "size": p.current_size_usd,
                    "entry": p.avg_entry_price,
                    "current": p.current_price,
                    "pnl": p.unrealized_pnl,
                    "pnl_pct": p.unrealized_pnl_pct,
                    "status": p.status.value,
                    "tier": p.tier,
                }
                for p in positions
            ],
        }
    
    def print_status(self):
        """Print formatted status to console."""
        status = self.get_status()
        
        print("\n" + "═" * 70)
        print("🤖 V6 ALPHA HUNTER STATUS")
        print("═" * 70)
        print(f"Mode: {status['mode']} | Running: {status['running']}")
        print(f"Last scan: {status['last_scan'] or 'Never'}")
        print(f"Scans: {status['stats']['scans_completed']} | "
              f"Opportunities: {status['stats']['opportunities_found']} | "
              f"Trades: {status['stats']['trades_executed']}")
        
        print("\n" + "─" * 70)
        print("💰 PORTFOLIO")
        print("─" * 70)
        p = status['portfolio']
        print(f"Bankroll:    ${p['total_bankroll']:,.2f}")
        print(f"Cash:        ${p['cash_available']:,.2f}")
        print(f"Exposure:    ${p['total_exposure']:,.2f} ({p['exposure_pct']:.1%})")
        print(f"Unrealized:  ${p['unrealized_pnl']:+,.2f}")
        print(f"Realized:    ${p['realized_pnl']:+,.2f}")
        
        print("\n" + "─" * 70)
        print("📊 POSITIONS")
        print("─" * 70)
        
        if not status['positions']:
            print("  (no active positions)")
        else:
            for pos in status['positions']:
                emoji = "🟢" if pos['pnl'] >= 0 else "🔴"
                print(f"{emoji} [{pos['direction']}] {pos['question']}")
                print(f"   Tier {pos['tier']}/3 | ${pos['size']:.2f} @ {pos['entry']:.4f} → {pos['current']:.4f}")
                print(f"   P&L: ${pos['pnl']:+.2f} ({pos['pnl_pct']:+.1%}) | {pos['status']}")
        
        print("═" * 70)
    
    def generate_learning_report(self) -> str:
        """Generate learning/performance report."""
        lines = []
        lines.append("\n" + "═" * 70)
        lines.append("📚 LEARNING REPORT")
        lines.append("═" * 70)
        
        # Category performance
        lines.append("\n📊 CATEGORY PERFORMANCE")
        lines.append("─" * 70)
        
        cat_stats = self.learning_loop.get_category_stats()
        if cat_stats:
            for cat, stats in sorted(cat_stats.items(), key=lambda x: x[1].accuracy, reverse=True):
                lines.append(
                    f"  {cat:15} | Trades: {stats.trades:3} | "
                    f"Win: {stats.accuracy:.0%} | "
                    f"P&L: ${stats.total_pnl:+.2f} | "
                    f"Weight: {stats.weight:.2f}"
                )
        else:
            lines.append("  (no data yet)")
        
        # Edge bucket performance
        lines.append("\n📈 EDGE BUCKET PERFORMANCE")
        lines.append("─" * 70)
        
        edge_stats = self.learning_loop.get_edge_bucket_stats()
        if edge_stats:
            for bucket, stats in sorted(edge_stats.items()):
                lines.append(
                    f"  {bucket:10}% edge | Trades: {stats['trades']:3} | "
                    f"Win: {stats['accuracy']:.0%} | "
                    f"Avg P&L: {stats['avg_pnl']:+.1f}%"
                )
        else:
            lines.append("  (no data yet)")
        
        # Recent trades
        lines.append("\n📜 RECENT TRADES")
        lines.append("─" * 70)
        
        recent = self.learning_loop.get_recent_trades(limit=10)
        if recent:
            for trade in recent:
                emoji = "✅" if trade['is_win'] else "❌"
                lines.append(
                    f"  {emoji} {trade['direction']} | {trade['category']:10} | "
                    f"Edge: {trade.get('edge_at_entry', 0)*100:+.1f}% | "
                    f"P&L: {trade['pnl']:+.1f}%"
                )
        else:
            lines.append("  (no trades yet)")
        
        lines.append("═" * 70)
        
        return "\n".join(lines)


# === CLI Entry Points ===

async def cmd_scan(config: BotConfig):
    """Run a single scan and display opportunities."""
    async with AlphaHunterBot(config) as bot:
        approved = await bot.run_full_scan()
        
        if not approved:
            print("\n❌ No approved opportunities found")
            return
        
        print(f"\n✅ Found {len(approved)} approved opportunities")
        print("\n" + "═" * 80)
        
        for i, score in enumerate(approved, 1):
            opp = score.research_result.opportunity
            research = score.research_result
            
            print(f"\n#{i} — CONVICTION: {score.score:.1f}/10 ({score.position_tier.upper()})")
            print(f"─" * 80)
            print(f"Question: {opp.question}")
            print(f"Direction: {opp.direction.value} @ {opp.market_price:.1%}")
            print(f"AI Estimate: {research.ai_estimate_post:.1%} (edge: {research.edge_pct_post:.1f}%)")
            print(f"Position Size: {score.recommended_position_pct:.1%} of portfolio")
            print(f"\nResearch Summary: {research.research_summary[:200]}...")
            print(f"\nSources: {len(research.sources)} ({research.recent_sources} recent)")
            
            if score.risk_flags:
                print(f"⚠️ Risks: {', '.join(score.risk_flags)}")
            
            print(f"URL: https://polymarket.com/event/{opp.slug}")


async def cmd_run(config: BotConfig, paper: bool = True, confirm_live: bool = False):
    """Run the trading bot."""
    if not paper and not confirm_live:
        print("❌ Live trading requires --confirm flag!")
        print("   Add --confirm to acknowledge you're trading real money")
        return
    
    config.paper_trading = paper
    
    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()
    
    async with AlphaHunterBot(config) as bot:
        def signal_handler():
            logger.info("Received shutdown signal...")
            bot._shutdown_event.set()
        
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)
        
        await bot.trading_loop()


async def cmd_status(config: BotConfig):
    """Show current status."""
    bot = AlphaHunterBot(config)
    bot.print_status()


async def cmd_report(config: BotConfig):
    """Generate learning report."""
    bot = AlphaHunterBot(config)
    report = bot.generate_learning_report()
    print(report)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="V6 Alpha Hunter — Polymarket Trading Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.bot scan              # Scan and show opportunities
  python -m src.bot run --paper       # Paper trading mode
  python -m src.bot run --live --confirm  # Live trading (real money!)
  python -m src.bot status            # Show current positions
  python -m src.bot report            # Show learning report
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Scan command
    scan_parser = subparsers.add_parser("scan", help="Run a single scan")
    scan_parser.add_argument("--max-markets", type=int, default=None, help="Limit markets to scan")
    scan_parser.add_argument("--top", type=int, default=50, help="Research top N opportunities")
    
    # Run command
    run_parser = subparsers.add_parser("run", help="Start the trading bot")
    run_parser.add_argument("--paper", action="store_true", default=True, help="Paper trading mode (default)")
    run_parser.add_argument("--live", action="store_true", help="Live trading mode")
    run_parser.add_argument("--confirm", action="store_true", help="Confirm live trading")
    run_parser.add_argument("--capital", type=float, default=10000, help="Initial capital")
    run_parser.add_argument("--interval", type=float, default=1.0, help="Hours between scans")
    
    # Status command
    status_parser = subparsers.add_parser("status", help="Show current status")
    
    # Report command
    report_parser = subparsers.add_parser("report", help="Generate learning report")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # Build config
    config = BotConfig()
    
    if args.command == "scan":
        config.max_markets_per_scan = args.max_markets
        config.top_opportunities_to_research = args.top
        asyncio.run(cmd_scan(config))
    
    elif args.command == "run":
        paper = not args.live
        config.initial_capital = args.capital
        config.scan_interval_hours = args.interval
        asyncio.run(cmd_run(config, paper=paper, confirm_live=args.confirm))
    
    elif args.command == "status":
        asyncio.run(cmd_status(config))
    
    elif args.command == "report":
        asyncio.run(cmd_report(config))


if __name__ == "__main__":
    main()
