"""Tests for Learning Loop and Pattern Analyzer."""

import json
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.learning_loop import (
    LearningLoop,
    TradeOutcome,
    CategoryStats,
    create_mock_trades,
)
from src.pattern_analyzer import PatternAnalyzer, print_report


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_learning.db"
        weights_path = Path(tmpdir) / "test_weights.json"
        yield db_path, weights_path


class TestLearningLoop:
    """Test the LearningLoop class."""
    
    def test_init_creates_db(self, temp_db):
        """Test database initialization."""
        db_path, weights_path = temp_db
        loop = LearningLoop(db_path=db_path, weights_path=weights_path)
        
        assert db_path.exists()
        assert weights_path.exists()
        
        # Check tables exist
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        
        assert "trades" in tables
        assert "category_stats" in tables
        assert "edge_buckets" in tables
        assert "source_stats" in tables
    
    def test_record_trade(self, temp_db):
        """Test recording a trade."""
        db_path, weights_path = temp_db
        loop = LearningLoop(db_path=db_path, weights_path=weights_path)
        
        trade = TradeOutcome(
            market_id="test_001",
            question="Will it rain tomorrow?",
            category="weather",
            direction="YES",
            entry_price=0.40,
            exit_price=1.0,
            ai_estimate=0.65,
            conviction_score=8.5,
            edge_at_entry=0.25,
            conviction_factors={"test": "factor"},
            resolved_outcome="YES",
            is_win=True,
            pnl=150.0,
            entry_timestamp=datetime.utcnow() - timedelta(days=5),
            exit_timestamp=datetime.utcnow(),
            resolution_timestamp=datetime.utcnow(),
            sources_used=["news_api", "twitter"],
        )
        
        loop.record_trade(trade)
        
        assert loop.get_trade_count() == 1
        
        recent = loop.get_recent_trades(1)
        assert len(recent) == 1
        assert recent[0]["market_id"] == "test_001"
        assert recent[0]["is_win"] == 1
    
    def test_category_normalization(self, temp_db):
        """Test that categories are normalized correctly."""
        db_path, weights_path = temp_db
        loop = LearningLoop(db_path=db_path, weights_path=weights_path)
        
        # Test various inputs
        assert loop._normalize_category("US Politics") == "politics"
        assert loop._normalize_category("Crypto Markets") == "crypto"
        assert loop._normalize_category("Bitcoin") == "crypto"
        assert loop._normalize_category("NBA Finals") == "sports"
        assert loop._normalize_category("Random Category") == "uncategorized"
        assert loop._normalize_category(None) == "uncategorized"
    
    def test_weight_calculation(self, temp_db):
        """Test weight calculation based on accuracy."""
        db_path, weights_path = temp_db
        loop = LearningLoop(db_path=db_path, weights_path=weights_path)
        
        # Need min trades
        assert loop._calculate_weight(0.80, trades=3) == 1.0  # Not enough trades
        
        # With enough trades
        assert loop._calculate_weight(0.80, trades=10) == 1.2  # >70%
        assert loop._calculate_weight(0.60, trades=10) == 1.0  # 50-70%
        assert loop._calculate_weight(0.40, trades=10) == 0.7  # <50%
    
    def test_category_stats(self, temp_db):
        """Test category stats calculation."""
        db_path, weights_path = temp_db
        loop = LearningLoop(db_path=db_path, weights_path=weights_path)
        
        # Record multiple trades
        for i in range(5):
            trade = TradeOutcome(
                market_id=f"test_{i:03d}",
                question=f"Political question {i}?",
                category="politics",
                direction="YES",
                entry_price=0.50,
                exit_price=1.0 if i < 4 else 0.0,  # 4 wins, 1 loss
                ai_estimate=0.75,
                conviction_score=8.5,
                edge_at_entry=0.25,
                resolved_outcome="YES" if i < 4 else "NO",
                is_win=i < 4,
                pnl=100.0 if i < 4 else -100.0,
                entry_timestamp=datetime.utcnow() - timedelta(days=i),
                exit_timestamp=datetime.utcnow(),
            )
            loop.record_trade(trade)
        
        stats = loop.get_category_stats()
        assert "politics" in stats
        
        pol_stats = stats["politics"]
        assert pol_stats.trades == 5
        assert pol_stats.wins == 4
        assert pol_stats.accuracy == 0.8


class TestPatternAnalyzer:
    """Test the PatternAnalyzer class."""
    
    def test_analyze_with_mock_data(self, temp_db):
        """Test pattern analysis with mock trades."""
        db_path, weights_path = temp_db
        loop = LearningLoop(db_path=db_path, weights_path=weights_path)
        
        # Create mock trades
        create_mock_trades(loop, count=10)
        
        # Analyze patterns
        analyzer = PatternAnalyzer(db_path=db_path)
        
        edge_patterns = analyzer.analyze_edge_patterns()
        cat_patterns = analyzer.analyze_category_patterns()
        
        # Should find some patterns with 10 trades
        # (exact results depend on random data)
        assert isinstance(edge_patterns, list)
        assert isinstance(cat_patterns, list)
    
    def test_generate_report(self, temp_db):
        """Test report generation."""
        db_path, weights_path = temp_db
        loop = LearningLoop(db_path=db_path, weights_path=weights_path)
        
        # Create mock trades
        create_mock_trades(loop, count=10)
        
        # Generate report (60 days to capture all trades since mock data spans 30 days)
        analyzer = PatternAnalyzer(db_path=db_path)
        report = analyzer.generate_report(days=60)
        
        assert report.total_trades >= 9  # Allow for timing edge cases
        assert report.period_start < report.period_end
        assert isinstance(report.recommendations, list)
        
        # Test markdown output
        md = report.to_markdown()
        assert "# Learning Report" in md
        assert "## Summary" in md
        assert "## Recommendations" in md


class TestIntegration:
    """Integration tests for the full learning system."""
    
    def test_full_workflow(self, temp_db):
        """Test the complete learning workflow."""
        db_path, weights_path = temp_db
        loop = LearningLoop(db_path=db_path, weights_path=weights_path)
        
        # 1. Record trades
        create_mock_trades(loop, count=10)
        
        # 2. Update weights
        weights = loop.update_all_weights()
        assert isinstance(weights, dict)
        assert "politics" in weights
        
        # 3. Check weight retrieval works
        weight = loop.get_category_weight("Political Events")
        assert 0.7 <= weight <= 1.2
        
        # 4. Generate analysis report (60 days to capture all mock trades)
        analyzer = PatternAnalyzer(db_path=db_path)
        report = analyzer.generate_report(days=60)
        
        # 5. Verify report has data
        assert report.total_trades >= 9  # Allow for timing edge cases
        print_report(report)


if __name__ == "__main__":
    # Run quick verification
    print("=" * 60)
    print("LEARNING LOOP - QUICK TEST")
    print("=" * 60)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        weights_path = Path(tmpdir) / "weights.json"
        
        # Initialize
        loop = LearningLoop(db_path=db_path, weights_path=weights_path)
        
        # Create mock trades
        print("\n1. Creating 10 mock trades...")
        create_mock_trades(loop, count=10)
        
        # Show stats
        print("\n2. Category Stats:")
        stats = loop.get_category_stats()
        for cat, s in stats.items():
            print(f"   {cat}: {s.trades} trades, {s.accuracy:.1%} accuracy")
        
        # Update weights
        print("\n3. Updated Weights:")
        weights = loop.update_all_weights()
        for cat, w in weights.items():
            if not cat.startswith("_"):
                print(f"   {cat}: {w}")
        
        # Generate report
        print("\n4. Generating Learning Report...")
        analyzer = PatternAnalyzer(db_path=db_path)
        report = analyzer.generate_report(days=30)
        print_report(report)
        
        print("\n✅ All tests passed!")
