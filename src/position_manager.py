"""Position Manager for V6 Alpha Hunter.

Handles:
- Scale-in (3 tiers with time gates)
- Take profit (4 levels)
- Stop loss (hard + trailing)
- SQLite persistence
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

from .models import (
    Position, PortfolioState, Direction, 
    PositionStatus, TakeProfitLevel, AlphaOpportunity, utcnow
)
from .risk_manager import RiskManager, RiskConfig


# ─────────────────────────────────────────────────────────────────────────────
# Database Schema
# ─────────────────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id TEXT NOT NULL,
    question TEXT NOT NULL,
    direction TEXT NOT NULL,
    
    tier INTEGER DEFAULT 0,
    target_size_usd REAL NOT NULL,
    current_size_usd REAL DEFAULT 0,
    avg_entry_price REAL DEFAULT 0,
    
    current_price REAL DEFAULT 0,
    peak_price REAL DEFAULT 0,
    
    unrealized_pnl REAL DEFAULT 0,
    realized_pnl REAL DEFAULT 0,
    unrealized_pnl_pct REAL DEFAULT 0,
    
    status TEXT DEFAULT 'PENDING',
    tp_level TEXT DEFAULT 'NONE',
    is_high_conviction INTEGER DEFAULT 0,
    
    created_at TEXT NOT NULL,
    last_tier_at TEXT,
    closed_at TEXT,
    
    notes TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_positions_market ON positions(market_id);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);

CREATE TABLE IF NOT EXISTS position_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    tier INTEGER,
    amount_usd REAL,
    price REAL,
    pnl REAL,
    notes TEXT,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (position_id) REFERENCES positions(id)
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    total_bankroll REAL NOT NULL,
    cash_available REAL NOT NULL,
    total_exposure REAL DEFAULT 0,
    unrealized_pnl REAL DEFAULT 0,
    realized_pnl REAL DEFAULT 0,
    position_count INTEGER DEFAULT 0,
    timestamp TEXT NOT NULL
);
"""


class PositionManager:
    """Manages trading positions with scaling and risk controls."""
    
    def __init__(
        self,
        db_path: str = "data/positions.db",
        risk_config: Optional[RiskConfig] = None,
        initial_bankroll: float = 10000.0
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.risk = RiskManager(risk_config)
        self.initial_bankroll = initial_bankroll
        
        self._init_db()
    
    # ─────────────────────────────────────────────────────────────────────────
    # Database Operations
    # ─────────────────────────────────────────────────────────────────────────
    
    def _init_db(self):
        """Initialize SQLite database with schema."""
        with self._db() as conn:
            conn.executescript(SCHEMA)
    
    @contextmanager
    def _db(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    
    def _position_from_row(self, row: sqlite3.Row) -> Position:
        """Convert a database row to a Position model."""
        return Position(
            id=row["id"],
            market_id=row["market_id"],
            question=row["question"],
            direction=Direction(row["direction"]),
            tier=row["tier"],
            target_size_usd=row["target_size_usd"],
            current_size_usd=row["current_size_usd"],
            avg_entry_price=row["avg_entry_price"],
            current_price=row["current_price"],
            peak_price=row["peak_price"],
            unrealized_pnl=row["unrealized_pnl"],
            realized_pnl=row["realized_pnl"],
            unrealized_pnl_pct=row["unrealized_pnl_pct"],
            status=PositionStatus(row["status"]),
            tp_level=TakeProfitLevel(row["tp_level"]),
            is_high_conviction=bool(row["is_high_conviction"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            last_tier_at=datetime.fromisoformat(row["last_tier_at"]) if row["last_tier_at"] else None,
            closed_at=datetime.fromisoformat(row["closed_at"]) if row["closed_at"] else None,
            notes=row["notes"] or ""
        )
    
    def _save_position(self, position: Position) -> int:
        """Save position to database, returns ID."""
        with self._db() as conn:
            if position.id:
                conn.execute("""
                    UPDATE positions SET
                        tier = ?, current_size_usd = ?, avg_entry_price = ?,
                        current_price = ?, peak_price = ?,
                        unrealized_pnl = ?, realized_pnl = ?, unrealized_pnl_pct = ?,
                        status = ?, tp_level = ?, last_tier_at = ?, closed_at = ?, notes = ?
                    WHERE id = ?
                """, (
                    position.tier, position.current_size_usd, position.avg_entry_price,
                    position.current_price, position.peak_price,
                    position.unrealized_pnl, position.realized_pnl, position.unrealized_pnl_pct,
                    position.status.value, position.tp_level.value,
                    position.last_tier_at.isoformat() if position.last_tier_at else None,
                    position.closed_at.isoformat() if position.closed_at else None,
                    position.notes, position.id
                ))
                return position.id
            else:
                cursor = conn.execute("""
                    INSERT INTO positions (
                        market_id, question, direction, tier, target_size_usd,
                        current_size_usd, avg_entry_price, current_price, peak_price,
                        unrealized_pnl, realized_pnl, unrealized_pnl_pct,
                        status, tp_level, is_high_conviction, created_at, last_tier_at, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    position.market_id, position.question, position.direction.value,
                    position.tier, position.target_size_usd,
                    position.current_size_usd, position.avg_entry_price,
                    position.current_price, position.peak_price,
                    position.unrealized_pnl, position.realized_pnl, position.unrealized_pnl_pct,
                    position.status.value, position.tp_level.value,
                    int(position.is_high_conviction),
                    position.created_at.isoformat(),
                    position.last_tier_at.isoformat() if position.last_tier_at else None,
                    position.notes
                ))
                return cursor.lastrowid
    
    def _log_action(self, position_id: int, action: str, tier: int = 0,
                    amount: float = 0, price: float = 0, pnl: float = 0, notes: str = ""):
        """Log a position action for audit trail."""
        with self._db() as conn:
            conn.execute("""
                INSERT INTO position_history (position_id, action, tier, amount_usd, price, pnl, notes, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (position_id, action, tier, amount, price, pnl, notes, utcnow().isoformat()))
    
    # ─────────────────────────────────────────────────────────────────────────
    # Portfolio State
    # ─────────────────────────────────────────────────────────────────────────
    
    def get_portfolio_state(self) -> PortfolioState:
        """Calculate current portfolio state from positions."""
        positions = self.get_active_positions()
        
        total_exposure = sum(p.current_size_usd for p in positions)
        unrealized_pnl = sum(p.unrealized_pnl for p in positions)
        realized_pnl = sum(p.realized_pnl for p in self.get_all_positions())
        
        # Cash = initial + realized P&L - exposure
        cash_available = self.initial_bankroll + realized_pnl - total_exposure
        total_bankroll = cash_available + total_exposure + unrealized_pnl
        
        sizes = [p.current_size_usd for p in positions]
        
        return PortfolioState(
            total_bankroll=total_bankroll,
            cash_available=cash_available,
            total_exposure=total_exposure,
            exposure_pct=total_exposure / total_bankroll if total_bankroll > 0 else 0,
            position_count=len(positions),
            unrealized_pnl=unrealized_pnl,
            realized_pnl=realized_pnl,
            largest_position_pct=max(sizes) / total_bankroll if sizes and total_bankroll > 0 else 0,
            avg_position_size=sum(sizes) / len(sizes) if sizes else 0
        )
    
    # ─────────────────────────────────────────────────────────────────────────
    # Position Queries
    # ─────────────────────────────────────────────────────────────────────────
    
    def get_position(self, position_id: int) -> Optional[Position]:
        """Get a position by ID."""
        with self._db() as conn:
            row = conn.execute("SELECT * FROM positions WHERE id = ?", (position_id,)).fetchone()
            return self._position_from_row(row) if row else None
    
    def get_position_by_market(self, market_id: str) -> Optional[Position]:
        """Get active position for a market."""
        with self._db() as conn:
            row = conn.execute("""
                SELECT * FROM positions 
                WHERE market_id = ? AND status NOT IN ('CLOSED', 'RESOLVED', 'STOPPED')
                ORDER BY created_at DESC LIMIT 1
            """, (market_id,)).fetchone()
            return self._position_from_row(row) if row else None
    
    def get_active_positions(self) -> list[Position]:
        """Get all active (non-closed) positions."""
        with self._db() as conn:
            rows = conn.execute("""
                SELECT * FROM positions 
                WHERE status NOT IN ('CLOSED', 'RESOLVED', 'STOPPED')
                ORDER BY created_at DESC
            """).fetchall()
            return [self._position_from_row(row) for row in rows]
    
    def get_all_positions(self) -> list[Position]:
        """Get all positions."""
        with self._db() as conn:
            rows = conn.execute("SELECT * FROM positions ORDER BY created_at DESC").fetchall()
            return [self._position_from_row(row) for row in rows]
    
    # ─────────────────────────────────────────────────────────────────────────
    # Position Entry (Scale-In)
    # ─────────────────────────────────────────────────────────────────────────
    
    def open_position(
        self,
        opportunity: AlphaOpportunity,
        target_size_usd: float,
        entry_price: float,
        is_high_conviction: bool = False
    ) -> tuple[Position, str]:
        """
        Open a new position at Tier 1 (33% of target).
        
        Returns (position, message).
        """
        portfolio = self.get_portfolio_state()
        
        # Check if already have position in this market
        existing = self.get_position_by_market(opportunity.market_id)
        if existing:
            return existing, f"Already have position in {opportunity.market_id}"
        
        # Risk check
        tier1_amount = self.risk.tier_size(target_size_usd, 1)
        can_open, reason = self.risk.check_can_open(portfolio, tier1_amount)
        if not can_open:
            return None, f"Cannot open position: {reason}"
        
        # Create position
        position = Position(
            market_id=opportunity.market_id,
            question=opportunity.question,
            direction=opportunity.direction,
            tier=1,
            target_size_usd=target_size_usd,
            current_size_usd=tier1_amount,
            avg_entry_price=entry_price,
            current_price=entry_price,
            peak_price=entry_price,
            status=PositionStatus.SCALING_IN,
            is_high_conviction=is_high_conviction,
            last_tier_at=utcnow(),
            notes=f"Opened with {opportunity.edge_pct:.1f}% edge"
        )
        
        position.id = self._save_position(position)
        self._log_action(position.id, "OPEN_TIER1", tier=1, amount=tier1_amount, price=entry_price,
                        notes=f"Edge: {opportunity.edge_pct:.1f}%")
        
        return position, f"✅ Opened Tier 1 (${tier1_amount:.2f}) @ {entry_price:.4f}"
    
    def scale_in(
        self,
        position: Position,
        current_price: float,
        thesis_confirmed: bool = True
    ) -> tuple[Position, str]:
        """
        Add to position (next scale-in tier).
        
        thesis_confirmed: Price moved our way OR new research confirms
        """
        portfolio = self.get_portfolio_state()
        
        # Risk check
        can_scale, reason = self.risk.check_can_scale_in(position, portfolio)
        if not can_scale:
            return position, f"Cannot scale in: {reason}"
        
        if not thesis_confirmed:
            return position, "Thesis not confirmed - skipping scale-in"
        
        next_tier = position.tier + 1
        tier_amount = self.risk.tier_size(position.target_size_usd, next_tier)
        
        # Calculate new average entry
        old_value = position.current_size_usd
        new_total = old_value + tier_amount
        new_avg = ((position.avg_entry_price * old_value) + (current_price * tier_amount)) / new_total
        
        # Update position
        position.tier = next_tier
        position.current_size_usd = new_total
        position.avg_entry_price = new_avg
        position.current_price = current_price
        position.peak_price = max(position.peak_price, current_price)
        position.last_tier_at = utcnow()
        
        if next_tier >= 3:
            position.status = PositionStatus.ACTIVE
        
        self._save_position(position)
        self._log_action(position.id, f"SCALE_TIER{next_tier}", tier=next_tier, 
                        amount=tier_amount, price=current_price)
        
        status = "FULLY SCALED" if next_tier >= 3 else f"Tier {next_tier}/3"
        return position, f"✅ Added ${tier_amount:.2f} @ {current_price:.4f} ({status})"
    
    # ─────────────────────────────────────────────────────────────────────────
    # Position Exit (Scale-Out / Stop Loss)
    # ─────────────────────────────────────────────────────────────────────────
    
    def take_profit(self, position: Position, current_price: float) -> tuple[Position, str]:
        """
        Execute take profit if conditions met.
        Sells 25% at each TP level.
        """
        self._update_position_prices(position, current_price)
        
        should_tp, sell_pct, reason = self.risk.check_take_profit(position)
        if not should_tp:
            return position, reason
        
        sell_amount = position.current_size_usd * sell_pct
        realized = sell_amount * position.unrealized_pnl_pct
        
        # Update position
        position.current_size_usd -= sell_amount
        position.realized_pnl += realized
        position.status = PositionStatus.SCALING_OUT
        
        # Advance TP level
        if position.tp_level == TakeProfitLevel.NONE:
            position.tp_level = TakeProfitLevel.TP1
        elif position.tp_level == TakeProfitLevel.TP1:
            position.tp_level = TakeProfitLevel.TP2
        elif position.tp_level == TakeProfitLevel.TP2:
            position.tp_level = TakeProfitLevel.TP3
        
        self._save_position(position)
        self._log_action(position.id, f"TAKE_PROFIT_{position.tp_level.value}",
                        amount=sell_amount, price=current_price, pnl=realized, notes=reason)
        
        return position, f"💰 {reason} - Sold ${sell_amount:.2f}, realized ${realized:.2f}"
    
    def stop_loss(self, position: Position, current_price: float) -> tuple[Position, str]:
        """
        Execute stop loss if conditions met.
        Exits 100% of position.
        """
        self._update_position_prices(position, current_price)
        
        should_stop, reason = self.risk.should_stop_loss(position)
        if not should_stop:
            return position, reason
        
        # Exit everything
        exit_amount = position.current_size_usd
        realized = exit_amount * position.unrealized_pnl_pct
        
        position.current_size_usd = 0
        position.realized_pnl += realized
        position.status = PositionStatus.STOPPED
        position.closed_at = utcnow()
        
        self._save_position(position)
        self._log_action(position.id, "STOP_LOSS", amount=exit_amount, price=current_price,
                        pnl=realized, notes=reason)
        
        return position, f"🛑 {reason} - Exited ${exit_amount:.2f}, realized ${realized:.2f}"
    
    def close_position(self, position: Position, current_price: float, reason: str = "") -> tuple[Position, str]:
        """Manually close entire position."""
        self._update_position_prices(position, current_price)
        
        exit_amount = position.current_size_usd
        realized = exit_amount * position.unrealized_pnl_pct
        
        position.current_size_usd = 0
        position.realized_pnl += realized
        position.status = PositionStatus.CLOSED
        position.closed_at = utcnow()
        position.notes += f"\nClosed: {reason}"
        
        self._save_position(position)
        self._log_action(position.id, "CLOSE", amount=exit_amount, price=current_price,
                        pnl=realized, notes=reason)
        
        return position, f"📤 Closed @ {current_price:.4f} - Realized ${realized:.2f}"
    
    def mark_resolved(self, position: Position, outcome_price: float) -> tuple[Position, str]:
        """Mark position as resolved (market ended)."""
        self._update_position_prices(position, outcome_price)
        
        # Final P&L based on outcome
        exit_amount = position.current_size_usd
        realized = exit_amount * position.unrealized_pnl_pct
        
        position.current_size_usd = 0
        position.realized_pnl += realized
        position.status = PositionStatus.RESOLVED
        position.closed_at = utcnow()
        
        self._save_position(position)
        self._log_action(position.id, "RESOLVED", amount=exit_amount, price=outcome_price,
                        pnl=realized, notes=f"Market resolved @ {outcome_price}")
        
        return position, f"🏁 Resolved @ {outcome_price:.4f} - Final P&L: ${position.realized_pnl:.2f}"
    
    # ─────────────────────────────────────────────────────────────────────────
    # Price Updates
    # ─────────────────────────────────────────────────────────────────────────
    
    def update_price(self, position: Position, current_price: float) -> Position:
        """Update position with new market price."""
        self._update_position_prices(position, current_price)
        self._save_position(position)
        return position
    
    def _update_position_prices(self, position: Position, current_price: float):
        """Internal: update P&L calculations based on new price."""
        position.current_price = current_price
        position.peak_price = max(position.peak_price, current_price)
        
        if position.avg_entry_price > 0 and position.current_size_usd > 0:
            if position.direction == Direction.NO:
                price_change_pct = (position.avg_entry_price - current_price) / position.avg_entry_price
            else:
                price_change_pct = (current_price - position.avg_entry_price) / position.avg_entry_price

            position.unrealized_pnl_pct = price_change_pct
            position.unrealized_pnl = position.current_size_usd * price_change_pct
    
    # ─────────────────────────────────────────────────────────────────────────
    # Monitoring Loop
    # ─────────────────────────────────────────────────────────────────────────
    
    def check_all_positions(self, price_fetcher: callable) -> list[str]:
        """
        Check all active positions for stop loss / take profit.
        
        price_fetcher: async function(market_id) -> current_price
        
        Returns list of actions taken.
        """
        actions = []
        
        for position in self.get_active_positions():
            try:
                current_price = price_fetcher(position.market_id)
                self._update_position_prices(position, current_price)
                
                # Check stop loss first
                position, msg = self.stop_loss(position, current_price)
                if "🛑" in msg:
                    actions.append(f"{position.question[:40]}... {msg}")
                    continue
                
                # Check take profit
                position, msg = self.take_profit(position, current_price)
                if "💰" in msg:
                    actions.append(f"{position.question[:40]}... {msg}")
                
            except Exception as e:
                actions.append(f"❌ Error updating {position.market_id}: {e}")
        
        return actions
    
    # ─────────────────────────────────────────────────────────────────────────
    # Reporting
    # ─────────────────────────────────────────────────────────────────────────
    
    def positions_summary(self) -> str:
        """Generate a summary of all positions."""
        positions = self.get_active_positions()
        portfolio = self.get_portfolio_state()
        
        lines = [
            "═" * 60,
            "📊 PORTFOLIO SUMMARY",
            "═" * 60,
            f"Bankroll:     ${portfolio.total_bankroll:,.2f}",
            f"Cash:         ${portfolio.cash_available:,.2f}",
            f"Exposure:     ${portfolio.total_exposure:,.2f} ({portfolio.exposure_pct:.1%})",
            f"Unrealized:   ${portfolio.unrealized_pnl:+,.2f}",
            f"Realized:     ${portfolio.realized_pnl:+,.2f}",
            f"Positions:    {portfolio.position_count}/{self.risk.config.max_concurrent_positions}",
            "",
            "─" * 60,
            "ACTIVE POSITIONS",
            "─" * 60,
        ]
        
        if not positions:
            lines.append("  (no active positions)")
        else:
            for p in positions:
                emoji = "🟢" if p.unrealized_pnl >= 0 else "🔴"
                lines.append(
                    f"{emoji} [{p.direction.value}] {p.question[:35]}...\n"
                    f"   Tier {p.tier}/3 | ${p.current_size_usd:.2f} @ {p.avg_entry_price:.4f} → {p.current_price:.4f}\n"
                    f"   P&L: ${p.unrealized_pnl:+.2f} ({p.unrealized_pnl_pct:+.1%}) | {p.status.value}"
                )
        
        lines.append("═" * 60)
        return "\n".join(lines)
    
    def position_history(self, position_id: int) -> list[dict]:
        """Get action history for a position."""
        with self._db() as conn:
            rows = conn.execute("""
                SELECT * FROM position_history 
                WHERE position_id = ? ORDER BY timestamp ASC
            """, (position_id,)).fetchall()
            return [dict(row) for row in rows]
