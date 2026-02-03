"""
Learning Loop — V6 Feedback System

Tracks trade outcomes, learns from patterns, and adjusts conviction weights.
"""

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

# Default paths
DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DATA_DIR / "learning.db"
WEIGHTS_PATH = DATA_DIR / "category_weights.json"


class TradeOutcome(BaseModel):
    """A completed trade with outcome data."""
    
    market_id: str
    question: str
    category: str = "uncategorized"
    
    # Trade details
    direction: str  # YES or NO
    entry_price: float = Field(ge=0, le=1)
    exit_price: float = Field(ge=0, le=1)
    
    # AI/Conviction data
    ai_estimate: float = Field(ge=0, le=1)
    conviction_score: float = Field(ge=0, le=10)
    edge_at_entry: float  # AI estimate - market price (signed)
    
    # Factors that contributed to conviction (JSON)
    conviction_factors: dict = Field(default_factory=dict)
    
    # Outcome
    resolved_outcome: str  # YES, NO, or INVALID
    is_win: bool
    pnl: float  # Profit/loss as percentage
    
    # Metadata
    entry_timestamp: datetime
    exit_timestamp: datetime
    resolution_timestamp: Optional[datetime] = None
    
    # Source info
    sources_used: list[str] = Field(default_factory=list)


class CategoryStats(BaseModel):
    """Performance statistics for a category."""
    
    category: str
    trades: int = 0
    wins: int = 0
    losses: int = 0
    
    accuracy: float = 0.0
    avg_edge: float = 0.0
    avg_pnl: float = 0.0
    total_pnl: float = 0.0
    
    # Weight for conviction engine
    weight: float = 1.0
    last_updated: datetime = Field(default_factory=datetime.utcnow)


class LearningLoop:
    """
    Learns from trade outcomes and adjusts conviction weights.
    
    Key responsibilities:
    - Store trade outcomes in SQLite
    - Calculate category accuracy
    - Adjust weights based on performance
    - Identify winning patterns
    """
    
    def __init__(self, db_path: Path = DB_PATH, weights_path: Path = WEIGHTS_PATH):
        self.db_path = db_path
        self.weights_path = weights_path
        self._init_db()
        self._load_weights()
    
    def _init_db(self):
        """Initialize SQLite database with tables."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Trades table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL,
                question TEXT,
                category TEXT DEFAULT 'uncategorized',
                
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                
                ai_estimate REAL,
                conviction_score REAL,
                edge_at_entry REAL,
                conviction_factors TEXT,
                
                resolved_outcome TEXT,
                is_win INTEGER,
                pnl REAL,
                
                entry_timestamp TEXT,
                exit_timestamp TEXT,
                resolution_timestamp TEXT,
                
                sources_used TEXT,
                
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Category stats cache
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS category_stats (
                category TEXT PRIMARY KEY,
                trades INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                accuracy REAL DEFAULT 0.0,
                avg_edge REAL DEFAULT 0.0,
                avg_pnl REAL DEFAULT 0.0,
                total_pnl REAL DEFAULT 0.0,
                weight REAL DEFAULT 1.0,
                last_updated TEXT
            )
        """)
        
        # Edge bucket performance
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS edge_buckets (
                bucket TEXT PRIMARY KEY,  -- e.g., "20-30", "30-40"
                trades INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                accuracy REAL DEFAULT 0.0,
                avg_pnl REAL DEFAULT 0.0
            )
        """)
        
        # Source reliability
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS source_stats (
                source_type TEXT PRIMARY KEY,
                trades INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                accuracy REAL DEFAULT 0.0
            )
        """)
        
        # Time to resolution stats
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS resolution_time_stats (
                time_bucket TEXT PRIMARY KEY,  -- e.g., "1-7days", "7-30days"
                trades INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                accuracy REAL DEFAULT 0.0
            )
        """)
        
        conn.commit()
        conn.close()
        logger.info(f"Database initialized at {self.db_path}")
    
    def _load_weights(self):
        """Load category weights from JSON file."""
        if self.weights_path.exists():
            with open(self.weights_path) as f:
                self.weights = json.load(f)
        else:
            self.weights = {
                "politics": 1.0,
                "crypto": 1.0,
                "sports": 1.0,
                "entertainment": 1.0,
                "science": 1.0,
                "tech": 1.0,
                "business": 1.0,
                "uncategorized": 1.0,
            }
            self._save_weights()
    
    def _save_weights(self):
        """Save category weights to JSON file."""
        self.weights_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.weights_path, "w") as f:
            json.dump(self.weights, f, indent=2)
        logger.info(f"Weights saved to {self.weights_path}")
    
    def get_category_weight(self, category: str) -> float:
        """Get the current weight for a category."""
        # Normalize category name
        cat = self._normalize_category(category)
        return self.weights.get(cat, 1.0)
    
    def _normalize_category(self, category: str) -> str:
        """Normalize category name to standard categories."""
        if not category:
            return "uncategorized"
        
        cat = category.lower()
        
        # Map to standard categories
        mappings = {
            "politics": ["politic", "election", "trump", "biden", "congress", "senate", "vote"],
            "crypto": ["crypto", "bitcoin", "ethereum", "btc", "eth", "defi", "nft"],
            "sports": ["sport", "nba", "nfl", "mlb", "soccer", "football", "basketball", "esport"],
            "entertainment": ["entertain", "movie", "music", "tv", "celebrity", "oscar"],
            "science": ["science", "space", "climate", "health", "medical", "covid"],
            "tech": ["tech", "ai", "apple", "google", "microsoft", "startup"],
            "business": ["business", "stock", "market", "econ", "finance", "fed"],
        }
        
        for std_cat, keywords in mappings.items():
            for kw in keywords:
                if kw in cat:
                    return std_cat
        
        return "uncategorized"
    
    # === Trade Recording ===
    
    def record_trade(self, trade: TradeOutcome):
        """Record a completed trade outcome."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Normalize category
        category = self._normalize_category(trade.category)
        
        cursor.execute("""
            INSERT INTO trades (
                market_id, question, category, direction,
                entry_price, exit_price, ai_estimate, conviction_score,
                edge_at_entry, conviction_factors, resolved_outcome,
                is_win, pnl, entry_timestamp, exit_timestamp,
                resolution_timestamp, sources_used
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade.market_id,
            trade.question,
            category,
            trade.direction,
            trade.entry_price,
            trade.exit_price,
            trade.ai_estimate,
            trade.conviction_score,
            trade.edge_at_entry,
            json.dumps(trade.conviction_factors),
            trade.resolved_outcome,
            1 if trade.is_win else 0,
            trade.pnl,
            trade.entry_timestamp.isoformat(),
            trade.exit_timestamp.isoformat(),
            trade.resolution_timestamp.isoformat() if trade.resolution_timestamp else None,
            json.dumps(trade.sources_used),
        ))
        
        conn.commit()
        conn.close()
        
        logger.info(f"Recorded trade: {trade.market_id} - {'WIN' if trade.is_win else 'LOSS'} ({trade.pnl:+.1f}%)")
        
        # Update stats
        self._update_category_stats(category)
        self._update_edge_bucket(trade.edge_at_entry, trade.is_win, trade.pnl)
        self._update_source_stats(trade.sources_used, trade.is_win)
        self._update_resolution_time_stats(trade)
    
    def _update_category_stats(self, category: str):
        """Recalculate stats for a category."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                COUNT(*) as trades,
                SUM(is_win) as wins,
                AVG(edge_at_entry) as avg_edge,
                AVG(pnl) as avg_pnl,
                SUM(pnl) as total_pnl
            FROM trades
            WHERE category = ?
        """, (category,))
        
        row = cursor.fetchone()
        trades, wins, avg_edge, avg_pnl, total_pnl = row
        
        wins = wins or 0
        accuracy = wins / trades if trades > 0 else 0.0
        
        cursor.execute("""
            INSERT OR REPLACE INTO category_stats
            (category, trades, wins, losses, accuracy, avg_edge, avg_pnl, total_pnl, weight, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            category,
            trades,
            wins,
            trades - wins,
            accuracy,
            avg_edge or 0,
            avg_pnl or 0,
            total_pnl or 0,
            self._calculate_weight(accuracy, trades),
            datetime.utcnow().isoformat(),
        ))
        
        conn.commit()
        conn.close()
    
    def _calculate_weight(self, accuracy: float, trades: int, min_trades: int = 5) -> float:
        """Calculate category weight based on accuracy."""
        # Need minimum trades for reliable stats
        if trades < min_trades:
            return 1.0
        
        if accuracy > 0.70:
            return 1.2
        elif accuracy >= 0.50:
            return 1.0
        else:
            return 0.7
    
    def _update_edge_bucket(self, edge: float, is_win: bool, pnl: float):
        """Update edge bucket statistics."""
        # Determine bucket (10% increments)
        edge_pct = abs(edge) * 100
        bucket_start = int(edge_pct // 10) * 10
        bucket = f"{bucket_start}-{bucket_start + 10}"
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get current stats
        cursor.execute("SELECT trades, wins, avg_pnl FROM edge_buckets WHERE bucket = ?", (bucket,))
        row = cursor.fetchone()
        
        if row:
            trades, wins, old_avg_pnl = row
            new_trades = trades + 1
            new_wins = wins + (1 if is_win else 0)
            new_avg_pnl = ((old_avg_pnl * trades) + pnl) / new_trades
        else:
            new_trades = 1
            new_wins = 1 if is_win else 0
            new_avg_pnl = pnl
        
        new_accuracy = new_wins / new_trades if new_trades > 0 else 0
        
        cursor.execute("""
            INSERT OR REPLACE INTO edge_buckets (bucket, trades, wins, accuracy, avg_pnl)
            VALUES (?, ?, ?, ?, ?)
        """, (bucket, new_trades, new_wins, new_accuracy, new_avg_pnl))
        
        conn.commit()
        conn.close()
    
    def _update_source_stats(self, sources: list[str], is_win: bool):
        """Update source reliability stats."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for source in sources:
            cursor.execute("SELECT trades, wins FROM source_stats WHERE source_type = ?", (source,))
            row = cursor.fetchone()
            
            if row:
                trades, wins = row
                new_trades = trades + 1
                new_wins = wins + (1 if is_win else 0)
            else:
                new_trades = 1
                new_wins = 1 if is_win else 0
            
            new_accuracy = new_wins / new_trades if new_trades > 0 else 0
            
            cursor.execute("""
                INSERT OR REPLACE INTO source_stats (source_type, trades, wins, accuracy)
                VALUES (?, ?, ?, ?)
            """, (source, new_trades, new_wins, new_accuracy))
        
        conn.commit()
        conn.close()
    
    def _update_resolution_time_stats(self, trade: TradeOutcome):
        """Update resolution time correlation stats."""
        if not trade.resolution_timestamp:
            return
        
        # Calculate days to resolution
        days = (trade.resolution_timestamp - trade.entry_timestamp).days
        
        # Determine time bucket
        if days <= 1:
            bucket = "0-1days"
        elif days <= 7:
            bucket = "1-7days"
        elif days <= 30:
            bucket = "7-30days"
        elif days <= 90:
            bucket = "30-90days"
        else:
            bucket = "90+days"
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT trades, wins FROM resolution_time_stats WHERE time_bucket = ?", (bucket,))
        row = cursor.fetchone()
        
        if row:
            trades, wins = row
            new_trades = trades + 1
            new_wins = wins + (1 if trade.is_win else 0)
        else:
            new_trades = 1
            new_wins = 1 if trade.is_win else 0
        
        new_accuracy = new_wins / new_trades if new_trades > 0 else 0
        
        cursor.execute("""
            INSERT OR REPLACE INTO resolution_time_stats (time_bucket, trades, wins, accuracy)
            VALUES (?, ?, ?, ?)
        """, (bucket, new_trades, new_wins, new_accuracy))
        
        conn.commit()
        conn.close()
    
    # === Stats Retrieval ===
    
    def get_category_stats(self) -> dict[str, CategoryStats]:
        """Get performance stats for all categories."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM category_stats")
        rows = cursor.fetchall()
        conn.close()
        
        stats = {}
        for row in rows:
            cat = row[0]
            stats[cat] = CategoryStats(
                category=cat,
                trades=row[1],
                wins=row[2],
                losses=row[3],
                accuracy=row[4],
                avg_edge=row[5],
                avg_pnl=row[6],
                total_pnl=row[7],
                weight=row[8],
                last_updated=datetime.fromisoformat(row[9]) if row[9] else datetime.utcnow(),
            )
        
        return stats
    
    def get_edge_bucket_stats(self) -> dict:
        """Get performance by edge size buckets."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM edge_buckets ORDER BY bucket")
        rows = cursor.fetchall()
        conn.close()
        
        return {
            row[0]: {
                "trades": row[1],
                "wins": row[2],
                "accuracy": row[3],
                "avg_pnl": row[4],
            }
            for row in rows
        }
    
    def get_source_stats(self) -> dict:
        """Get reliability stats for different source types."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM source_stats ORDER BY accuracy DESC")
        rows = cursor.fetchall()
        conn.close()
        
        return {
            row[0]: {
                "trades": row[1],
                "wins": row[2],
                "accuracy": row[3],
            }
            for row in rows
        }
    
    def get_resolution_time_stats(self) -> dict:
        """Get accuracy by time-to-resolution."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM resolution_time_stats")
        rows = cursor.fetchall()
        conn.close()
        
        return {
            row[0]: {
                "trades": row[1],
                "wins": row[2],
                "accuracy": row[3],
            }
            for row in rows
        }
    
    # === Weight Updates ===
    
    def update_all_weights(self) -> dict[str, float]:
        """Update weights for all categories based on recent performance."""
        stats = self.get_category_stats()
        
        for cat, cat_stats in stats.items():
            new_weight = self._calculate_weight(cat_stats.accuracy, cat_stats.trades)
            self.weights[cat] = new_weight
            
            logger.info(
                f"Category '{cat}': accuracy={cat_stats.accuracy:.1%}, "
                f"trades={cat_stats.trades}, weight={new_weight}"
            )
        
        self._save_weights()
        return self.weights.copy()
    
    def should_update_weights(self, days: int = 7) -> bool:
        """Check if it's time to update weights (weekly by default)."""
        if not self.weights_path.exists():
            return True
        
        mtime = datetime.fromtimestamp(self.weights_path.stat().st_mtime)
        return datetime.now() - mtime > timedelta(days=days)
    
    # === Recent Trades ===
    
    def get_recent_trades(self, limit: int = 20) -> list[dict]:
        """Get most recent trades."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM trades
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_trade_count(self) -> int:
        """Get total number of recorded trades."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM trades")
        count = cursor.fetchone()[0]
        conn.close()
        return count


# === Convenience Functions ===

def create_mock_trades(loop: LearningLoop, count: int = 10):
    """Create mock trade history for testing."""
    import random
    
    categories = ["politics", "crypto", "sports", "entertainment", "tech"]
    sources = ["news_api", "twitter", "reddit", "official_source", "ai_analysis"]
    
    base_time = datetime.utcnow() - timedelta(days=30)
    
    for i in range(count):
        category = random.choice(categories)
        direction = random.choice(["YES", "NO"])
        entry_price = random.uniform(0.3, 0.7)
        ai_estimate = entry_price + random.uniform(-0.1, 0.3)
        ai_estimate = max(0.1, min(0.9, ai_estimate))
        edge = ai_estimate - entry_price
        
        # Higher edge = higher win rate (simulating edge working)
        win_prob = 0.5 + abs(edge) * 1.5  # Edge adds to win probability
        is_win = random.random() < min(0.85, win_prob)
        
        if is_win:
            exit_price = 1.0 if direction == "YES" else 0.0
            resolved = direction
        else:
            exit_price = 0.0 if direction == "YES" else 1.0
            resolved = "NO" if direction == "YES" else "YES"
        
        pnl = ((exit_price - entry_price) / entry_price) * 100
        if direction == "NO":
            pnl = ((entry_price - exit_price) / entry_price) * 100
        
        entry_time = base_time + timedelta(days=i * 2)
        resolution_days = random.randint(1, 60)
        
        trade = TradeOutcome(
            market_id=f"mock_{i:04d}",
            question=f"Mock question about {category} #{i}?",
            category=category,
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            ai_estimate=ai_estimate,
            conviction_score=random.uniform(7.5, 9.5),
            edge_at_entry=edge,
            conviction_factors={
                "ai_confidence": random.uniform(0.7, 0.95),
                "source_agreement": random.uniform(0.6, 0.9),
                "volume_signal": random.choice(["high", "medium", "low"]),
            },
            resolved_outcome=resolved,
            is_win=is_win,
            pnl=pnl,
            entry_timestamp=entry_time,
            exit_timestamp=entry_time + timedelta(days=resolution_days - 1),
            resolution_timestamp=entry_time + timedelta(days=resolution_days),
            sources_used=random.sample(sources, k=random.randint(2, 4)),
        )
        
        loop.record_trade(trade)
    
    logger.info(f"Created {count} mock trades")


if __name__ == "__main__":
    # Test the learning loop
    loop = LearningLoop()
    
    print("Creating mock trades...")
    create_mock_trades(loop, 10)
    
    print("\n" + "=" * 60)
    print("CATEGORY STATS")
    print("=" * 60)
    
    stats = loop.get_category_stats()
    for cat, s in stats.items():
        print(f"{cat:15} | Trades: {s.trades:3} | Wins: {s.wins:3} | "
              f"Accuracy: {s.accuracy:.1%} | Weight: {s.weight}")
    
    print("\n" + "=" * 60)
    print("EDGE BUCKET PERFORMANCE")
    print("=" * 60)
    
    edge_stats = loop.get_edge_bucket_stats()
    for bucket, s in edge_stats.items():
        print(f"{bucket:10} | Trades: {s['trades']:3} | Accuracy: {s['accuracy']:.1%}")
    
    print("\n" + "=" * 60)
    print("SOURCE RELIABILITY")
    print("=" * 60)
    
    source_stats = loop.get_source_stats()
    for source, s in source_stats.items():
        print(f"{source:20} | Trades: {s['trades']:3} | Accuracy: {s['accuracy']:.1%}")
    
    print("\n" + "=" * 60)
    print("UPDATED WEIGHTS")
    print("=" * 60)
    
    weights = loop.update_all_weights()
    for cat, w in weights.items():
        print(f"{cat:15} | Weight: {w}")
