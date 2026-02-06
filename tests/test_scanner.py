"""Tests for Alpha Scanner."""

import pytest
from datetime import datetime

from src.models import AlphaOpportunity, Direction, Market, ScanResult
from src.config import V6Config


class TestModels:
    """Test Pydantic models."""
    
    def test_market_yes_price(self):
        market = Market(
            id="123",
            question="Test?",
            slug="test",
            outcome_prices=[0.65, 0.35],
        )
        assert market.yes_price == 0.65
        assert market.no_price == 0.35
    
    def test_alpha_opportunity_str(self):
        opp = AlphaOpportunity(
            market_id="123",
            question="Will Bitcoin reach $100k?",
            slug="btc-100k",
            market_price=0.45,
            ai_estimate=0.70,
            edge_pct=25.0,
            direction=Direction.YES,
        )
        assert "25.0% edge" in str(opp)
        assert "YES" in str(opp)
    
    def test_direction_values(self):
        assert Direction.YES.value == "YES"
        assert Direction.NO.value == "NO"


class TestConfig:
    """Test configuration."""
    
    def test_default_config(self):
        cfg = V6Config()
        assert cfg.alpha_threshold == 0.20
        assert cfg.ollama_model == "qwen2.5:32b"
        assert cfg.min_conviction == 8
    
    def test_custom_config(self):
        cfg = V6Config(alpha_threshold=0.15, batch_size=50)
        assert cfg.alpha_threshold == 0.15
        assert cfg.batch_size == 50


class TestScanResult:
    """Test scan result model."""
    
    def test_scan_result_empty(self):
        result = ScanResult(
            total_markets_scanned=100,
            markets_with_alpha=0,
            opportunities=[],
            scan_duration_sec=60.5,
        )
        assert result.total_markets_scanned == 100
        assert result.markets_with_alpha == 0
        assert len(result.opportunities) == 0
    
    def test_scan_result_with_opportunities(self):
        opp = AlphaOpportunity(
            market_id="123",
            question="Test?",
            slug="test",
            market_price=0.40,
            ai_estimate=0.65,
            edge_pct=25.0,
            direction=Direction.YES,
        )
        result = ScanResult(
            total_markets_scanned=100,
            markets_with_alpha=1,
            opportunities=[opp],
            scan_duration_sec=60.5,
        )
        assert len(result.opportunities) == 1
        assert result.opportunities[0].edge_pct == 25.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
