"""
Conviction Engine — V6 Core Component

Scores trade opportunities based on multiple factors to determine
whether to trade and at what position size.

Factors & Weights:
- Edge size (25%): How big is the mispricing?
- Source quality (20%): Reuters/AP vs blogs vs nothing
- Source agreement (20%): Do sources agree or conflict?
- Recency (15%): How fresh is the information?
- AI confidence delta (10%): Did research strengthen conviction?
- Category track record (10%): Historical performance in this category
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .models import (
    ConvictionBreakdown,
    ConvictionScore,
    Direction,
    ResearchResult,
    SourceTier,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

# Weight constants
WEIGHT_EDGE_SIZE = 0.25
WEIGHT_SOURCE_QUALITY = 0.20
WEIGHT_SOURCE_AGREEMENT = 0.20
WEIGHT_RECENCY = 0.15
WEIGHT_AI_CONFIDENCE_DELTA = 0.10
WEIGHT_CATEGORY_TRACK_RECORD = 0.10

# Position sizing thresholds
CONVICTION_THRESHOLD = 8.0
POSITION_STANDARD = 0.03  # 3%
POSITION_LARGE = 0.05     # 5%
POSITION_MAX = 0.07       # 7%

# High-quality source domains
TIER1_SOURCES = {
    "reuters.com", "apnews.com", "gov.uk", "whitehouse.gov",
    "sec.gov", "federalreserve.gov", "ecb.europa.eu", "bls.gov",
    "congress.gov", "un.org", "who.int", "worldbank.org",
    ".gov", ".edu"  # General government/educational domains
}

TIER2_SOURCES = {
    "bbc.com", "bbc.co.uk", "nytimes.com", "washingtonpost.com",
    "wsj.com", "ft.com", "economist.com", "bloomberg.com",
    "cnbc.com", "cnn.com", "theguardian.com", "politico.com",
    "axios.com", "npr.org", "pbs.org", "cbsnews.com", "nbcnews.com",
    "forbes.com", "businessinsider.com", "techcrunch.com"
}


class ConvictionEngine:
    """Scores research results to determine trade conviction."""
    
    def __init__(self, category_weights_path: Optional[Path] = None):
        """
        Initialize the conviction engine.
        
        Args:
            category_weights_path: Path to category weights JSON file
        """
        if category_weights_path is None:
            category_weights_path = Path(__file__).parent / "category_weights.json"
        
        self.category_weights_path = category_weights_path
        self.category_weights = self._load_category_weights()
    
    def _load_category_weights(self) -> dict[str, float]:
        """Load category track record weights from file."""
        if self.category_weights_path.exists():
            try:
                with open(self.category_weights_path) as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load category weights: {e}")
        return {}  # Empty dict means all categories get default 1.0
    
    def save_category_weights(self):
        """Save current category weights to file."""
        with open(self.category_weights_path, 'w') as f:
            json.dump(self.category_weights, f, indent=2)
    
    def update_category_weight(self, category: str, was_correct: bool, confidence: float = 1.0):
        """
        Update category weight based on trade outcome.
        
        Uses exponential moving average to update weights.
        """
        current = self.category_weights.get(category, 1.0)
        
        # Result: 1.0 if correct, 0.0 if wrong
        result = 1.0 if was_correct else 0.0
        
        # EMA with alpha=0.2 (recent results matter more)
        alpha = 0.2
        new_weight = alpha * result + (1 - alpha) * current
        
        # Clamp between 0.3 and 1.5
        self.category_weights[category] = max(0.3, min(1.5, new_weight))
        self.save_category_weights()
    
    # === Factor Scoring Functions ===
    
    def _score_edge_size(self, edge_pct: float) -> float:
        """
        Score based on edge magnitude.
        
        20-30% edge = 6
        30-50% edge = 8
        50%+ edge = 10
        Below 20% shouldn't be here but gets 2
        """
        if edge_pct >= 50:
            return 10.0
        elif edge_pct >= 40:
            return 9.0
        elif edge_pct >= 30:
            return 8.0
        elif edge_pct >= 25:
            return 7.0
        elif edge_pct >= 20:
            return 6.0
        elif edge_pct >= 15:
            return 4.0
        else:
            return 2.0
    
    def _classify_source_tier(self, url: str) -> SourceTier:
        """Classify a source URL into quality tiers."""
        url_lower = url.lower()
        
        # Check for tier 1 (official/government)
        for domain in TIER1_SOURCES:
            if domain in url_lower:
                return SourceTier.TIER1
        
        # Check for tier 2 (major news)
        for domain in TIER2_SOURCES:
            if domain in url_lower:
                return SourceTier.TIER2
        
        # Everything else is tier 3
        return SourceTier.TIER3
    
    def _score_source_quality(self, sources: list[str]) -> float:
        """
        Score based on best source quality.
        
        Reuters/AP (Tier1) = 10
        Major news (Tier2) = 7
        Blogs/social (Tier3) = 5
        No sources = 2
        """
        if not sources:
            return 2.0
        
        tiers = [self._classify_source_tier(url) for url in sources]
        
        if SourceTier.TIER1 in tiers:
            # Bonus for multiple tier1 sources
            tier1_count = tiers.count(SourceTier.TIER1)
            return min(10.0, 9.0 + tier1_count * 0.5)
        elif SourceTier.TIER2 in tiers:
            tier2_count = tiers.count(SourceTier.TIER2)
            return min(8.0, 6.0 + tier2_count * 0.5)
        else:
            return 5.0
    
    def _score_source_agreement(self, research: ResearchResult) -> float:
        """
        Score based on whether sources agree on the outcome.
        
        All agree = 10
        Mixed signals = 5
        Conflict = 2
        
        Uses key_facts and research_summary to infer agreement.
        """
        # If we have very few sources, be conservative
        if len(research.sources) < 2:
            return 5.0
        
        # Check if AI confidence strengthened (suggests sources agreed with original thesis)
        if research.conviction_strengthened:
            # Large strengthening = strong agreement
            if abs(research.confidence_delta) > 0.10:
                return 10.0
            elif abs(research.confidence_delta) > 0.05:
                return 8.0
            else:
                return 7.0
        else:
            # Conviction weakened - sources may have disagreed
            if abs(research.confidence_delta) > 0.15:
                # Big shift away = strong conflict
                return 2.0
            elif abs(research.confidence_delta) > 0.05:
                return 4.0
            else:
                # Small change either way = mixed/neutral
                return 5.0
    
    def _score_recency(self, research: ResearchResult) -> float:
        """
        Score based on information freshness.
        
        Sources from <24h = 10
        Sources from <7d = 7
        Older = 4
        
        Uses recent_sources count from research.
        """
        total = len(research.sources)
        if total == 0:
            return 4.0
        
        # Calculate ratio of recent sources
        recent_ratio = research.recent_sources / total
        
        if recent_ratio >= 0.8:
            return 10.0
        elif recent_ratio >= 0.6:
            return 9.0
        elif recent_ratio >= 0.4:
            return 8.0
        elif recent_ratio >= 0.2:
            return 7.0
        elif research.recent_sources > 0:
            return 6.0
        else:
            return 4.0
    
    def _score_ai_confidence_delta(self, research: ResearchResult) -> float:
        """
        Score based on how AI confidence changed after research.
        
        Conviction increased = 10
        Stayed same = 6
        Decreased = 2
        """
        delta = research.confidence_delta
        direction = research.opportunity.direction
        
        # For YES direction, positive delta is good
        # For NO direction, negative delta is good (lower probability = more NO)
        if direction == Direction.YES:
            effective_delta = delta
        else:
            effective_delta = -delta
        
        if effective_delta > 0.10:
            return 10.0
        elif effective_delta > 0.05:
            return 9.0
        elif effective_delta > 0.02:
            return 8.0
        elif effective_delta > -0.02:
            return 6.0  # Essentially unchanged
        elif effective_delta > -0.05:
            return 4.0
        else:
            return 2.0
    
    def _score_category_track_record(self, category: Optional[str]) -> float:
        """
        Score based on historical performance in this category.
        
        Uses learned weights from past trades.
        Default 1.0 weight = score of 5
        """
        if not category:
            return 5.0  # Neutral for uncategorized
        
        weight = self.category_weights.get(category, 1.0)
        
        # Map weight (0.3-1.5) to score (2-10)
        # weight 0.3 → 2, weight 1.0 → 6, weight 1.5 → 10
        score = 2 + (weight - 0.3) * (8 / 1.2)
        return max(2.0, min(10.0, score))
    
    # === Main Scoring ===
    
    def score(self, research: ResearchResult) -> ConvictionScore:
        """
        Calculate conviction score for a researched opportunity.
        
        Returns ConvictionScore with full breakdown and trade decision.
        """
        opp = research.opportunity
        
        # Calculate individual factor scores
        edge_score = self._score_edge_size(research.edge_pct_post)
        quality_score = self._score_source_quality(research.sources)
        agreement_score = self._score_source_agreement(research)
        recency_score = self._score_recency(research)
        delta_score = self._score_ai_confidence_delta(research)
        category_score = self._score_category_track_record(opp.category)
        
        breakdown = ConvictionBreakdown(
            edge_size=edge_score,
            source_quality=quality_score,
            source_agreement=agreement_score,
            recency=recency_score,
            ai_confidence_delta=delta_score,
            category_track_record=category_score,
        )
        
        # Calculate weighted total
        total = (
            edge_score * WEIGHT_EDGE_SIZE +
            quality_score * WEIGHT_SOURCE_QUALITY +
            agreement_score * WEIGHT_SOURCE_AGREEMENT +
            recency_score * WEIGHT_RECENCY +
            delta_score * WEIGHT_AI_CONFIDENCE_DELTA +
            category_score * WEIGHT_CATEGORY_TRACK_RECORD
        )
        
        # Risk flags
        risk_flags = []
        if quality_score < 5:
            risk_flags.append("Low source quality")
        if agreement_score < 5:
            risk_flags.append("Source conflict detected")
        if recency_score < 5:
            risk_flags.append("Stale information")
        if delta_score < 5:
            risk_flags.append("AI confidence decreased")
        if opp.liquidity < 5000:
            risk_flags.append("Low liquidity")
        
        # Determine position sizing
        trade_approved = total >= CONVICTION_THRESHOLD
        
        if total >= 9.5:
            position_pct = POSITION_MAX
            position_tier = "max"
        elif total >= 9.0:
            position_pct = POSITION_LARGE
            position_tier = "large"
        elif total >= CONVICTION_THRESHOLD:
            position_pct = POSITION_STANDARD
            position_tier = "standard"
        else:
            position_pct = 0.0
            position_tier = "none"
        
        # Build reasoning
        reasoning_parts = [
            f"Edge: {research.edge_pct_post:.1f}% ({edge_score:.0f}/10)",
            f"Sources: {len(research.sources)} found, quality {quality_score:.0f}/10",
            f"Agreement: {agreement_score:.0f}/10",
            f"Recency: {research.recent_sources}/{len(research.sources)} recent ({recency_score:.0f}/10)",
            f"AI delta: {research.confidence_delta:+.1%} ({delta_score:.0f}/10)",
            f"Category '{opp.category}': {category_score:.0f}/10",
        ]
        
        if risk_flags:
            reasoning_parts.append(f"⚠️ Risks: {', '.join(risk_flags)}")
        
        reasoning = " | ".join(reasoning_parts)
        
        return ConvictionScore(
            research_result=research,
            score=round(total, 2),
            breakdown=breakdown,
            trade_approved=trade_approved,
            recommended_position_pct=position_pct,
            position_tier=position_tier,
            reasoning=reasoning,
            risk_flags=risk_flags,
        )
    
    def score_batch(self, research_results: list[ResearchResult]) -> list[ConvictionScore]:
        """Score multiple research results and return sorted by conviction."""
        scores = [self.score(r) for r in research_results]
        return sorted(scores, key=lambda x: x.score, reverse=True)


# === Convenience functions ===

def create_engine() -> ConvictionEngine:
    """Create a ConvictionEngine instance with default settings."""
    return ConvictionEngine()


def score_opportunity(research: ResearchResult) -> ConvictionScore:
    """Score a single research result."""
    engine = create_engine()
    return engine.score(research)


# === Demo / Testing ===

def _create_mock_research(
    question: str,
    category: str,
    market_price: float,
    ai_pre: float,
    ai_post: float,
    sources: list[str],
    recent_sources: int,
) -> ResearchResult:
    """Create mock research result for testing."""
    from .models import AlphaOpportunity, Direction
    
    edge = abs(ai_pre - market_price) * 100
    direction = Direction.YES if ai_pre > market_price else Direction.NO
    
    opp = AlphaOpportunity(
        market_id=f"mock-{hash(question) % 10000}",
        question=question,
        category=category,
        slug=question.lower().replace(" ", "-")[:30],
        market_price=market_price,
        ai_estimate=ai_pre,
        edge_pct=edge,
        direction=direction,
        volume_24h=50000,
        liquidity=25000,
    )
    
    return ResearchResult(
        opportunity=opp,
        research_summary=f"Mock research for: {question}",
        sources=sources,
        key_facts=[f"Key fact {i+1}" for i in range(3)],
        ai_estimate_pre=ai_pre,
        ai_estimate_post=ai_post,
        confidence_delta=ai_post - ai_pre,
        queries_run=5,
        results_found=len(sources),
        recent_sources=recent_sources,
        research_duration_sec=12.5,
    )


def demo():
    """Demo the conviction engine with mock data."""
    
    # Create test scenarios
    test_cases = [
        # Strong case: big edge, good sources, recent, conviction strengthened
        _create_mock_research(
            question="Will Bitcoin reach $100k by March 2026?",
            category="Crypto",
            market_price=0.35,
            ai_pre=0.65,
            ai_post=0.72,
            sources=[
                "https://reuters.com/bitcoin-analysis",
                "https://bloomberg.com/crypto-outlook",
                "https://wsj.com/bitcoin-etf",
            ],
            recent_sources=3,
        ),
        # Medium case: decent edge, mixed sources
        _create_mock_research(
            question="Will Tesla stock hit $400 by Q2 2026?",
            category="Stocks",
            market_price=0.40,
            ai_pre=0.62,
            ai_post=0.58,
            sources=[
                "https://nytimes.com/tesla-analysis",
                "https://reddit.com/r/stocks/tesla",
            ],
            recent_sources=1,
        ),
        # Weak case: small edge, no good sources, old info
        _create_mock_research(
            question="Will a specific policy pass by end of 2026?",
            category="Politics",
            market_price=0.50,
            ai_pre=0.72,
            ai_post=0.65,
            sources=[
                "https://randomblog.com/politics",
            ],
            recent_sources=0,
        ),
        # Edge case: huge edge but weak sources
        _create_mock_research(
            question="Will obscure event happen?",
            category="Other",
            market_price=0.20,
            ai_pre=0.75,
            ai_post=0.70,
            sources=[],
            recent_sources=0,
        ),
        # Strong: government source, recent
        _create_mock_research(
            question="Will Fed raise rates in Q1 2026?",
            category="Economics",
            market_price=0.30,
            ai_pre=0.58,
            ai_post=0.65,
            sources=[
                "https://federalreserve.gov/monetarypolicy",
                "https://wsj.com/fed-rates",
                "https://ft.com/fed-policy",
            ],
            recent_sources=2,
        ),
        # Sports with good sources
        _create_mock_research(
            question="Will Lakers make playoffs 2026?",
            category="Sports",
            market_price=0.45,
            ai_pre=0.70,
            ai_post=0.72,
            sources=[
                "https://espn.com/nba/lakers",
                "https://nytimes.com/sports/basketball",
            ],
            recent_sources=2,
        ),
        # Huge edge, tier 1 sources
        _create_mock_research(
            question="Will specific bill pass Senate?",
            category="Politics",
            market_price=0.25,
            ai_pre=0.80,
            ai_post=0.85,
            sources=[
                "https://congress.gov/bill",
                "https://apnews.com/politics",
                "https://politico.com/bill-analysis",
            ],
            recent_sources=3,
        ),
        # Moderate with mixed signals
        _create_mock_research(
            question="Will Apple launch new product?",
            category="Tech",
            market_price=0.60,
            ai_pre=0.35,
            ai_post=0.40,
            sources=[
                "https://techcrunch.com/apple-rumors",
                "https://macrumors.com/leak",
            ],
            recent_sources=1,
        ),
        # Weak conviction - AI went opposite way
        _create_mock_research(
            question="Will merger complete by deadline?",
            category="Business",
            market_price=0.70,
            ai_pre=0.45,
            ai_post=0.55,
            sources=[
                "https://bloomberg.com/mergers",
                "https://wsj.com/business",
            ],
            recent_sources=2,
        ),
        # Very strong - all factors align
        _create_mock_research(
            question="Will major treaty be signed?",
            category="World",
            market_price=0.30,
            ai_pre=0.65,
            ai_post=0.75,
            sources=[
                "https://un.org/treaties",
                "https://reuters.com/world",
                "https://apnews.com/international",
                "https://bbc.com/news/world",
            ],
            recent_sources=4,
        ),
    ]
    
    engine = ConvictionEngine()
    scores = engine.score_batch(test_cases)
    
    print("\n" + "=" * 80)
    print("CONVICTION ENGINE — TOP 10 OPPORTUNITIES")
    print("=" * 80)
    
    approved_count = 0
    
    for i, score in enumerate(scores, 1):
        opp = score.research_result.opportunity
        status = "✅" if score.trade_approved else "❌"
        
        print(f"\n{i}. {status} Score: {score.score:.1f}/10 | Position: {score.position_tier.upper()} ({score.recommended_position_pct:.0%})")
        print(f"   {opp.question[:70]}...")
        print(f"   Edge: {score.research_result.edge_pct_post:.1f}% {opp.direction.value} | Category: {opp.category}")
        print(f"   Breakdown: Edge={score.breakdown.edge_size:.0f} Quality={score.breakdown.source_quality:.0f} "
              f"Agree={score.breakdown.source_agreement:.0f} Recent={score.breakdown.recency:.0f} "
              f"Delta={score.breakdown.ai_confidence_delta:.0f} Track={score.breakdown.category_track_record:.0f}")
        
        if score.risk_flags:
            print(f"   ⚠️  {', '.join(score.risk_flags)}")
        
        if score.trade_approved:
            approved_count += 1
    
    print("\n" + "=" * 80)
    print(f"SUMMARY: {approved_count}/{len(scores)} opportunities approved for trading")
    print("=" * 80)
    
    return scores


if __name__ == "__main__":
    demo()
