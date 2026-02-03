"""
SQLite persistence layer for alpha scanner results.
"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
import threading

@dataclass
class ScanResult:
    """Phase 1 scan result."""
    id: Optional[int] = None
    market_id: str = ""
    question: str = ""
    market_price: float = 0.0
    ai_estimate: float = 0.0
    edge: float = 0.0
    confidence: float = 0.0
    reasoning: str = ""
    scanned_at: str = ""
    phase: int = 1
    
    # Phase 2 fields
    researched_at: Optional[str] = None
    research_summary: Optional[str] = None
    validated_edge: Optional[float] = None
    final_decision: Optional[str] = None

class Database:
    """Thread-safe SQLite database for scan results."""
    
    def __init__(self, db_path: str = "data/scans.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()
    
    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local connection."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn
    
    def _init_schema(self):
        """Initialize database schema."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS scan_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT UNIQUE NOT NULL,
                question TEXT NOT NULL,
                market_price REAL NOT NULL,
                ai_estimate REAL NOT NULL,
                edge REAL NOT NULL,
                confidence REAL NOT NULL,
                reasoning TEXT,
                scanned_at TEXT NOT NULL,
                phase INTEGER DEFAULT 1,
                
                -- Phase 2 fields
                researched_at TEXT,
                research_summary TEXT,
                validated_edge REAL,
                final_decision TEXT,
                
                -- Indexes
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE INDEX IF NOT EXISTS idx_edge ON scan_results(edge);
            CREATE INDEX IF NOT EXISTS idx_phase ON scan_results(phase);
            CREATE INDEX IF NOT EXISTS idx_market_id ON scan_results(market_id);
            CREATE INDEX IF NOT EXISTS idx_final_decision ON scan_results(final_decision);
        """)
        conn.commit()
    
    def upsert_scan(self, result: ScanResult) -> int:
        """Insert or update a scan result."""
        conn = self._get_conn()
        cursor = conn.execute("""
            INSERT INTO scan_results (
                market_id, question, market_price, ai_estimate, edge,
                confidence, reasoning, scanned_at, phase
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(market_id) DO UPDATE SET
                question = excluded.question,
                market_price = excluded.market_price,
                ai_estimate = excluded.ai_estimate,
                edge = excluded.edge,
                confidence = excluded.confidence,
                reasoning = excluded.reasoning,
                scanned_at = excluded.scanned_at,
                phase = excluded.phase
        """, (
            result.market_id, result.question, result.market_price,
            result.ai_estimate, result.edge, result.confidence,
            result.reasoning, result.scanned_at, result.phase
        ))
        conn.commit()
        return cursor.lastrowid
    
    def update_research(self, market_id: str, research_summary: str,
                       validated_edge: float, final_decision: str) -> bool:
        """Update Phase 2 research results."""
        conn = self._get_conn()
        cursor = conn.execute("""
            UPDATE scan_results SET
                researched_at = ?,
                research_summary = ?,
                validated_edge = ?,
                final_decision = ?,
                phase = 2
            WHERE market_id = ?
        """, (
            datetime.utcnow().isoformat(),
            research_summary,
            validated_edge,
            final_decision,
            market_id
        ))
        conn.commit()
        return cursor.rowcount > 0
    
    def get_phase1_candidates(self, min_edge: float = 0.05) -> List[ScanResult]:
        """Get Phase 1 results with edge above threshold for Phase 2 processing."""
        conn = self._get_conn()
        cursor = conn.execute("""
            SELECT * FROM scan_results
            WHERE edge >= ? AND (phase = 1 OR researched_at IS NULL)
            ORDER BY edge DESC
        """, (min_edge,))
        return [self._row_to_result(row) for row in cursor.fetchall()]
    
    def get_results(self, min_edge: float = 0.0, phase: Optional[int] = None,
                   final_decision: Optional[str] = None,
                   limit: int = 100) -> List[ScanResult]:
        """Get scan results with filters."""
        conn = self._get_conn()
        query = "SELECT * FROM scan_results WHERE edge >= ?"
        params: List[Any] = [min_edge]
        
        if phase is not None:
            query += " AND phase = ?"
            params.append(phase)
        
        if final_decision is not None:
            query += " AND final_decision = ?"
            params.append(final_decision)
        
        query += " ORDER BY edge DESC LIMIT ?"
        params.append(limit)
        
        cursor = conn.execute(query, params)
        return [self._row_to_result(row) for row in cursor.fetchall()]
    
    def get_alpha_opportunities(self, min_validated_edge: float = 0.05) -> List[ScanResult]:
        """Get confirmed alpha opportunities from Phase 2."""
        conn = self._get_conn()
        cursor = conn.execute("""
            SELECT * FROM scan_results
            WHERE phase = 2 
            AND final_decision = 'BUY'
            AND validated_edge >= ?
            ORDER BY validated_edge DESC
        """, (min_validated_edge,))
        return [self._row_to_result(row) for row in cursor.fetchall()]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        conn = self._get_conn()
        stats = {}
        
        cursor = conn.execute("SELECT COUNT(*) FROM scan_results")
        stats['total_scans'] = cursor.fetchone()[0]
        
        cursor = conn.execute("SELECT COUNT(*) FROM scan_results WHERE phase = 1")
        stats['phase1_only'] = cursor.fetchone()[0]
        
        cursor = conn.execute("SELECT COUNT(*) FROM scan_results WHERE phase = 2")
        stats['phase2_complete'] = cursor.fetchone()[0]
        
        cursor = conn.execute("SELECT COUNT(*) FROM scan_results WHERE edge >= 0.05")
        stats['candidates'] = cursor.fetchone()[0]
        
        cursor = conn.execute("SELECT COUNT(*) FROM scan_results WHERE final_decision = 'BUY'")
        stats['buy_signals'] = cursor.fetchone()[0]
        
        cursor = conn.execute("SELECT AVG(edge) FROM scan_results WHERE edge >= 0.05")
        stats['avg_edge'] = cursor.fetchone()[0] or 0
        
        return stats
    
    def clear_all(self):
        """Clear all scan results."""
        conn = self._get_conn()
        conn.execute("DELETE FROM scan_results")
        conn.commit()
    
    def _row_to_result(self, row: sqlite3.Row) -> ScanResult:
        """Convert database row to ScanResult."""
        return ScanResult(
            id=row['id'],
            market_id=row['market_id'],
            question=row['question'],
            market_price=row['market_price'],
            ai_estimate=row['ai_estimate'],
            edge=row['edge'],
            confidence=row['confidence'],
            reasoning=row['reasoning'],
            scanned_at=row['scanned_at'],
            phase=row['phase'],
            researched_at=row['researched_at'],
            research_summary=row['research_summary'],
            validated_edge=row['validated_edge'],
            final_decision=row['final_decision']
        )
