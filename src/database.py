"""SQLite database wrapper for Polymarket V6."""
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Tuple
from contextlib import contextmanager

from .models import Market


class Database:
    """SQLite database wrapper with upsert and maintenance operations."""
    
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS markets (
        id TEXT PRIMARY KEY,
        question TEXT NOT NULL,
        description TEXT,
        category TEXT,
        end_date TEXT,
        
        -- Prices (updated frequently)
        yes_price REAL,
        no_price REAL,
        
        -- Metrics
        volume REAL DEFAULT 0,
        liquidity REAL DEFAULT 0,
        
        -- Status tracking
        status TEXT DEFAULT 'active',
        first_seen_at TEXT,
        last_updated_at TEXT,
        resolved_at TEXT,
        
        -- Research data
        researched_at TEXT,
        research_summary TEXT,
        
        -- AI analysis (with research context)
        ai_probability REAL,
        ai_confidence REAL,
        ai_reasoning TEXT,
        analyzed_at TEXT,
        
        -- Trading signals
        edge REAL,
        signal TEXT,
        recommended_size REAL,

        -- Phase 2 validation (optional)
        validated_edge REAL,
        final_decision TEXT
    );
    
    CREATE INDEX IF NOT EXISTS idx_status ON markets(status);
    CREATE INDEX IF NOT EXISTS idx_edge ON markets(edge);
    CREATE INDEX IF NOT EXISTS idx_first_seen ON markets(first_seen_at);
    CREATE INDEX IF NOT EXISTS idx_signal ON markets(signal);
    CREATE INDEX IF NOT EXISTS idx_analyzed ON markets(analyzed_at);
    """
    
    def __init__(self, db_path: str = "data/markets.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Initialize database with schema."""
        with self._connect() as conn:
            conn.executescript(self.SCHEMA)
    
    @contextmanager
    def _connect(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    
    def upsert_market(self, market: Market) -> bool:
        """
        Upsert a market. Returns True if this is a NEW market.
        Preserves first_seen_at and research data for existing markets.
        """
        now = datetime.utcnow().isoformat()
        
        with self._connect() as conn:
            # Check if market exists
            existing = conn.execute(
                "SELECT id, first_seen_at, researched_at, research_summary, "
                "ai_probability, ai_confidence, ai_reasoning, analyzed_at, "
                "edge, signal, recommended_size FROM markets WHERE id = ?",
                (market.id,)
            ).fetchone()
            
            is_new = existing is None
            
            if is_new:
                # New market - insert with first_seen_at
                market.first_seen_at = now
                market.last_updated_at = now
            else:
                # Existing market - preserve research and analysis data
                market.first_seen_at = existing["first_seen_at"]
                market.last_updated_at = now
                
                # Keep existing research if not provided
                if not market.researched_at:
                    market.researched_at = existing["researched_at"]
                    market.research_summary = existing["research_summary"]
                
                # Keep existing analysis if not provided
                if not market.analyzed_at:
                    market.analyzed_at = existing["analyzed_at"]
                    market.ai_probability = existing["ai_probability"]
                    market.ai_confidence = existing["ai_confidence"]
                    market.ai_reasoning = existing["ai_reasoning"]
                    market.edge = existing["edge"]
                    market.signal = existing["signal"]
                    market.recommended_size = existing["recommended_size"]
            
            # Upsert
            conn.execute("""
                INSERT OR REPLACE INTO markets (
                    id, question, description, category, end_date,
                    yes_price, no_price, volume, liquidity, status,
                    first_seen_at, last_updated_at, resolved_at,
                    researched_at, research_summary,
                    ai_probability, ai_confidence, ai_reasoning, analyzed_at,
                    edge, signal, recommended_size,
                    validated_edge, final_decision
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                market.id, market.question, market.description, market.category, market.end_date,
                market.yes_price, market.no_price, market.volume, market.liquidity, market.status,
                market.first_seen_at, market.last_updated_at, market.resolved_at,
                market.researched_at, market.research_summary,
                market.ai_probability, market.ai_confidence, market.ai_reasoning, market.analyzed_at,
                market.edge, market.signal, market.recommended_size,
                None, None
            ))
            
            return is_new
    
    def upsert_markets(self, markets: List[Market]) -> List[str]:
        """Upsert multiple markets. Returns list of NEW market IDs."""
        new_ids = []
        for market in markets:
            if self.upsert_market(market):
                new_ids.append(market.id)
        return new_ids
    
    def get_market(self, market_id: str) -> Optional[Market]:
        """Get a single market by ID."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM markets WHERE id = ?", (market_id,)).fetchone()
            if row:
                return self._row_to_market(row)
        return None
    
    def get_markets(self, 
                    status: Optional[str] = None,
                    needs_research: bool = False,
                    needs_analysis: bool = False,
                    has_signal: Optional[str] = None,
                    min_edge: Optional[float] = None,
                    limit: Optional[int] = None) -> List[Market]:
        """Get markets with filters."""
        query = "SELECT * FROM markets WHERE 1=1"
        params = []
        
        if status:
            query += " AND status = ?"
            params.append(status)
        
        if needs_research:
            query += " AND (researched_at IS NULL OR researched_at < date('now', '-7 days'))"
        
        if needs_analysis:
            query += " AND researched_at IS NOT NULL AND (analyzed_at IS NULL OR analyzed_at < researched_at)"
        
        if has_signal:
            query += " AND signal = ?"
            params.append(has_signal)
        
        if min_edge is not None:
            query += " AND edge >= ?"
            params.append(min_edge)
        
        query += " ORDER BY first_seen_at DESC"
        
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_market(row) for row in rows]
    
    def get_new_markets(self, since_hours: int = 24) -> List[Market]:
        """Get markets first seen in the last N hours."""
        query = """
            SELECT * FROM markets 
            WHERE first_seen_at > datetime('now', ?)
            ORDER BY first_seen_at DESC
        """
        with self._connect() as conn:
            rows = conn.execute(query, (f'-{since_hours} hours',)).fetchall()
            return [self._row_to_market(row) for row in rows]
    
    def get_opportunities(self, min_edge: float = 0.05, min_confidence: float = 0.6) -> List[Market]:
        """Get markets with positive edge and high confidence."""
        query = """
            SELECT * FROM markets 
            WHERE signal = 'BUY' 
            AND edge >= ? 
            AND ai_confidence >= ?
            AND status = 'active'
            ORDER BY edge DESC
        """
        with self._connect() as conn:
            rows = conn.execute(query, (min_edge, min_confidence)).fetchall()
            return [self._row_to_market(row) for row in rows]
    
    def update_research(self, market_id: str, research_summary: str,
                        validated_edge: Optional[float] = None,
                        final_decision: Optional[str] = None):
        """Update research data for a market."""
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute("""
                UPDATE markets 
                SET research_summary = ?,
                    researched_at = ?,
                    last_updated_at = ?,
                    validated_edge = COALESCE(?, validated_edge),
                    final_decision = COALESCE(?, final_decision)
                WHERE id = ?
            """, (research_summary, now, now, validated_edge, final_decision, market_id))

    def get_phase1_candidates(self, min_edge: float = 0.05) -> List["AlphaOpportunity"]:
        """Return Phase 1 candidates as alpha opportunities."""
        from .models import AlphaOpportunity, Direction

        query = """
            SELECT id, question, category, yes_price, ai_probability, edge, ai_reasoning,
                   volume, liquidity
            FROM markets
            WHERE status = 'active'
              AND ai_probability IS NOT NULL
              AND edge IS NOT NULL
              AND ABS(edge) >= ?
            ORDER BY ABS(edge) DESC
        """
        with self._connect() as conn:
            rows = conn.execute(query, (min_edge,)).fetchall()

        candidates = []
        for row in rows:
            market_price = row["yes_price"] or 0.5
            ai_estimate = row["ai_probability"]
            edge = ai_estimate - market_price
            direction = Direction.YES if edge >= 0 else Direction.NO
            candidates.append(
                AlphaOpportunity(
                    market_id=row["id"],
                    question=row["question"],
                    category=row["category"],
                    slug=row["id"],
                    market_price=market_price,
                    ai_estimate=ai_estimate,
                    edge_pct=abs(edge) * 100,
                    direction=direction,
                    volume_24h=row["volume"] or 0.0,
                    liquidity=row["liquidity"] or 0.0,
                    reasoning=row["ai_reasoning"],
                )
            )

        return candidates
    
    def update_analysis(self, market_id: str, probability: float, confidence: float, 
                        reasoning: str, edge: float, signal: str, recommended_size: float):
        """Update AI analysis for a market."""
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute("""
                UPDATE markets 
                SET ai_probability = ?, ai_confidence = ?, ai_reasoning = ?,
                    edge = ?, signal = ?, recommended_size = ?,
                    analyzed_at = ?, last_updated_at = ?
                WHERE id = ?
            """, (probability, confidence, reasoning, edge, signal, recommended_size, now, now, market_id))
    
    def mark_resolved(self, market_id: str):
        """Mark a market as resolved."""
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute("""
                UPDATE markets 
                SET status = 'resolved', resolved_at = ?, last_updated_at = ?
                WHERE id = ?
            """, (now, now, market_id))
    
    def maintenance(self) -> dict:
        """
        Run maintenance tasks:
        - Remove very old resolved markets (>30 days)
        - Return stats
        """
        stats = {}
        
        with self._connect() as conn:
            # Count by status
            for status in ['active', 'resolved', 'closed']:
                count = conn.execute(
                    "SELECT COUNT(*) FROM markets WHERE status = ?", (status,)
                ).fetchone()[0]
                stats[f"{status}_count"] = count
            
            # Remove old resolved markets
            result = conn.execute("""
                DELETE FROM markets 
                WHERE status = 'resolved' 
                AND resolved_at < datetime('now', '-30 days')
            """)
            stats["purged_old_resolved"] = result.rowcount
            
            # Count markets needing research
            stats["needs_research"] = conn.execute("""
                SELECT COUNT(*) FROM markets 
                WHERE status = 'active' 
                AND (researched_at IS NULL OR researched_at < datetime('now', '-7 days'))
            """).fetchone()[0]
            
            # Count markets needing analysis
            stats["needs_analysis"] = conn.execute("""
                SELECT COUNT(*) FROM markets 
                WHERE status = 'active'
                AND researched_at IS NOT NULL 
                AND (analyzed_at IS NULL OR analyzed_at < researched_at)
            """).fetchone()[0]
            
            # Total markets
            stats["total"] = conn.execute("SELECT COUNT(*) FROM markets").fetchone()[0]
        
        return stats
    
    def get_stats(self) -> dict:
        """Get database statistics."""
        with self._connect() as conn:
            stats = {
                "total": conn.execute("SELECT COUNT(*) FROM markets").fetchone()[0],
                "active": conn.execute("SELECT COUNT(*) FROM markets WHERE status = 'active'").fetchone()[0],
                "resolved": conn.execute("SELECT COUNT(*) FROM markets WHERE status = 'resolved'").fetchone()[0],
                "with_research": conn.execute("SELECT COUNT(*) FROM markets WHERE researched_at IS NOT NULL").fetchone()[0],
                "with_analysis": conn.execute("SELECT COUNT(*) FROM markets WHERE analyzed_at IS NOT NULL").fetchone()[0],
                "buy_signals": conn.execute("SELECT COUNT(*) FROM markets WHERE signal = 'BUY'").fetchone()[0],
            }
        return stats
    
    def _row_to_market(self, row: sqlite3.Row) -> Market:
        """Convert a database row to a Market object."""
        return Market(
            id=row["id"],
            question=row["question"],
            description=row["description"],
            category=row["category"],
            end_date=row["end_date"],
            yes_price=row["yes_price"],
            no_price=row["no_price"],
            volume=row["volume"],
            liquidity=row["liquidity"],
            status=row["status"],
            first_seen_at=row["first_seen_at"],
            last_updated_at=row["last_updated_at"],
            resolved_at=row["resolved_at"],
            researched_at=row["researched_at"],
            research_summary=row["research_summary"],
            ai_probability=row["ai_probability"],
            ai_confidence=row["ai_confidence"],
            ai_reasoning=row["ai_reasoning"],
            analyzed_at=row["analyzed_at"],
            edge=row["edge"],
            signal=row["signal"],
            recommended_size=row["recommended_size"],
        )
