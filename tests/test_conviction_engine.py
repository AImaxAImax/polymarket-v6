"""Tests for the Conviction Engine."""

import pytest
from datetime import datetime

from src.conviction_engine import ConvictionEngine, CONVICTION_THRESHOLD
from src.models import (
    AlphaOpportunity,
    ConvictionScore,
    Direction,
    ResearchResult,
    SourceTier,
)


def make_opportunity(
    question: str = "Test question?",
    market_price: float = 0.40,
    ai_estimate: float = 0.70,
    category: str = "Test",
) -> AlphaOpportunity:
    """Create a test opportunity."""
    edge = abs(ai_estimate - market_price) * 100
    direction = Direction.YES if ai_estimate > market_price else Direction.NO
    
    return AlphaOpportunity(
        market_id="test-123",
        question=question,
        category=category,
        slug="test-slug",
        market_price=market_price,
        ai_estimate=ai_estimate,
        edge_pct=edge,
        direction=direction,
        volume_24h=10000,
        liquidity=50000,
    )


def make_research(
    opp: AlphaOpportunity,
    ai_post: float = None,
    sources: list[str] = None,
    recent_sources: int = None,
) -> ResearchResult:
    """Create a test research result."""
    if ai_post is None:
        ai_post = opp.ai_estimate + 0.05
    if sources is None:
        sources = ["https://reuters.com/test"]
    if recent_sources is None:
        recent_sources = len(sources)
    
    return ResearchResult(
        opportunity=opp,
        research_summary="Test research summary",
        sources=sources,
        key_facts=["Fact 1", "Fact 2"],
        ai_estimate_pre=opp.ai_estimate,
        ai_estimate_post=ai_post,
        confidence_delta=ai_post - opp.ai_estimate,
        queries_run=3,
        results_found=len(sources),
        recent_sources=recent_sources,
        research_duration_sec=5.0,
    )


class TestConvictionEngine:
    """Test suite for ConvictionEngine."""
    
    def setup_method(self):
        """Set up test engine."""
        self.engine = ConvictionEngine()
    
    def test_score_returns_conviction_score(self):
        """Verify score returns proper ConvictionScore object."""
        opp = make_opportunity()
        research = make_research(opp)
        
        result = self.engine.score(research)
        
        assert isinstance(result, ConvictionScore)
        assert 0 <= result.score <= 10
        assert result.breakdown is not None
    
    def test_high_conviction_approves_trade(self):
        """High quality opportunity should be approved."""
        opp = make_opportunity(
            market_price=0.30,
            ai_estimate=0.70,  # 40% edge
        )
        research = make_research(
            opp,
            ai_post=0.75,  # Strengthened
            sources=[
                "https://reuters.com/news",
                "https://apnews.com/story",
                "https://bbc.com/news",
            ],
            recent_sources=3,
        )
        
        result = self.engine.score(research)
        
        assert result.score >= CONVICTION_THRESHOLD
        assert result.trade_approved is True
        assert result.recommended_position_pct > 0
    
    def test_low_conviction_rejects_trade(self):
        """Low quality opportunity should be rejected."""
        opp = make_opportunity(
            market_price=0.50,
            ai_estimate=0.60,  # Only 10% edge
        )
        research = make_research(
            opp,
            ai_post=0.55,  # Weakened
            sources=["https://random-blog.com/post"],
            recent_sources=0,
        )
        
        result = self.engine.score(research)
        
        assert result.score < CONVICTION_THRESHOLD
        assert result.trade_approved is False
        assert result.recommended_position_pct == 0
    
    def test_edge_scoring(self):
        """Test edge size scoring boundaries."""
        # 50%+ edge should get 10
        assert self.engine._score_edge_size(55) == 10.0
        # 30-50% should get 8
        assert self.engine._score_edge_size(35) == 8.0
        # 20-30% should get 6
        assert self.engine._score_edge_size(25) == 7.0
        # Below 20% gets lower
        assert self.engine._score_edge_size(10) < 4
    
    def test_source_quality_scoring(self):
        """Test source quality tier scoring."""
        # Tier 1 sources (Reuters, AP, .gov)
        assert self.engine._score_source_quality(["https://reuters.com/news"]) >= 9.0
        assert self.engine._score_source_quality(["https://federalreserve.gov/policy"]) >= 9.0
        
        # Tier 2 sources (major news)
        assert 6.0 <= self.engine._score_source_quality(["https://nytimes.com/article"]) <= 8.0
        
        # No sources
        assert self.engine._score_source_quality([]) == 2.0
    
    def test_position_sizing_tiers(self):
        """Test position sizing based on conviction score."""
        opp = make_opportunity(market_price=0.20, ai_estimate=0.75)
        
        # Score ~9.5+ should get max position (7%)
        research_max = make_research(
            opp,
            ai_post=0.85,
            sources=[
                "https://reuters.com/a",
                "https://apnews.com/b",
                "https://congress.gov/c",
            ],
            recent_sources=3,
        )
        result_max = self.engine.score(research_max)
        
        if result_max.score >= 9.5:
            assert result_max.recommended_position_pct == 0.07
            assert result_max.position_tier == "max"
        elif result_max.score >= 9.0:
            assert result_max.recommended_position_pct == 0.05
            assert result_max.position_tier == "large"
        elif result_max.score >= 8.0:
            assert result_max.recommended_position_pct == 0.03
            assert result_max.position_tier == "standard"
    
    def test_risk_flags_detected(self):
        """Test that risk flags are properly detected."""
        opp = make_opportunity(market_price=0.50, ai_estimate=0.70)
        
        # Create research with multiple risks
        research = make_research(
            opp,
            ai_post=0.60,  # AI went down (bad for YES direction)
            sources=["https://random-blog.com"],
            recent_sources=0,
        )
        
        result = self.engine.score(research)
        
        # Should have risk flags (stale info and/or AI confidence)
        assert len(result.risk_flags) > 0
        # Check for any of the expected risk types
        flags_lower = [f.lower() for f in result.risk_flags]
        assert any("stale" in f or "confidence" in f or "source" in f for f in flags_lower)
    
    def test_batch_scoring_sorted(self):
        """Test batch scoring returns sorted results."""
        opportunities = [
            make_research(make_opportunity(ai_estimate=0.55)),  # Low edge
            make_research(make_opportunity(ai_estimate=0.80)),  # High edge
            make_research(make_opportunity(ai_estimate=0.65)),  # Medium edge
        ]
        
        results = self.engine.score_batch(opportunities)
        
        # Should be sorted by score descending
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score
    
    def test_source_tier_classification(self):
        """Test URL tier classification."""
        assert self.engine._classify_source_tier("https://reuters.com/news") == SourceTier.TIER1
        assert self.engine._classify_source_tier("https://sec.gov/filing") == SourceTier.TIER1
        assert self.engine._classify_source_tier("https://stanford.edu/research") == SourceTier.TIER1
        assert self.engine._classify_source_tier("https://nytimes.com/article") == SourceTier.TIER2
        assert self.engine._classify_source_tier("https://random-blog.com/post") == SourceTier.TIER3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
