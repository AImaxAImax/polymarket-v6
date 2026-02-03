"""Pydantic models for Polymarket V6 Alpha Hunter."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


def utcnow() -> datetime:
    """Get current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


class Direction(str, Enum):
    YES = "YES"
    NO = "NO"


class PositionStatus(str, Enum):
    """Position lifecycle status."""
    PENDING = "PENDING"          # Awaiting entry
    SCALING_IN = "SCALING_IN"    # Partially filled, more tiers to go
    ACTIVE = "ACTIVE"            # Fully scaled in
    SCALING_OUT = "SCALING_OUT"  # Taking profit
    STOPPED = "STOPPED"          # Hit stop loss
    CLOSED = "CLOSED"            # Fully exited
    RESOLVED = "RESOLVED"        # Market resolved


class TakeProfitLevel(str, Enum):
    """Take profit tiers hit."""
    NONE = "NONE"
    TP1 = "TP1"    # +15% - sold 25%
    TP2 = "TP2"    # +25% - sold 50% total
    TP3 = "TP3"    # +40% - sold 75% total
    FULL = "FULL"  # Resolved or fully exited


class Position(BaseModel):
    """A trading position in a market."""
    
    id: Optional[int] = None
    market_id: str
    question: str
    direction: Direction
    
    # Entry tracking
    tier: int = 0                          # 0=pending, 1-3=scale-in tiers
    target_size_usd: float                 # Full target position size
    current_size_usd: float = 0            # Current position size
    avg_entry_price: float = 0             # Volume-weighted avg entry
    
    # Price tracking
    current_price: float = 0
    peak_price: float = 0                  # Highest price since entry (for trailing)
    
    # P&L
    unrealized_pnl: float = 0
    realized_pnl: float = 0
    unrealized_pnl_pct: float = 0
    
    # Status
    status: PositionStatus = PositionStatus.PENDING
    tp_level: TakeProfitLevel = TakeProfitLevel.NONE
    is_high_conviction: bool = False       # No stop loss if True
    
    # Timestamps
    created_at: datetime = Field(default_factory=utcnow)
    last_tier_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    
    # Audit trail
    notes: str = ""
    
    def can_add_tier(self, min_hours: float = 4.0) -> bool:
        """Check if enough time has passed to add another tier."""
        if self.tier >= 3:
            return False
        if self.last_tier_at is None:
            return True
        elapsed = (utcnow() - self.last_tier_at).total_seconds() / 3600
        return elapsed >= min_hours
    
    @property
    def shares_held(self) -> float:
        """Approximate shares held (size / avg_entry)."""
        if self.avg_entry_price <= 0:
            return 0
        return self.current_size_usd / self.avg_entry_price


class PortfolioState(BaseModel):
    """Current state of the portfolio."""
    
    total_bankroll: float
    cash_available: float
    total_exposure: float = 0              # Sum of all position sizes
    exposure_pct: float = 0                # exposure / bankroll
    
    position_count: int = 0
    unrealized_pnl: float = 0
    realized_pnl: float = 0
    
    # Risk metrics
    largest_position_pct: float = 0
    avg_position_size: float = 0
    
    timestamp: datetime = Field(default_factory=utcnow)
    
    def can_open_position(self, size_usd: float, max_single_pct: float = 0.10, 
                          max_total_pct: float = 0.50, max_positions: int = 10) -> tuple[bool, str]:
        """Check if a new position can be opened."""
        if self.position_count >= max_positions:
            return False, f"Max positions ({max_positions}) reached"
        
        position_pct = size_usd / self.total_bankroll if self.total_bankroll > 0 else 1
        if position_pct > max_single_pct:
            return False, f"Position too large: {position_pct:.1%} > {max_single_pct:.1%}"
        
        new_exposure_pct = (self.total_exposure + size_usd) / self.total_bankroll if self.total_bankroll > 0 else 1
        if new_exposure_pct > max_total_pct:
            return False, f"Would exceed max exposure: {new_exposure_pct:.1%} > {max_total_pct:.1%}"
        
        if size_usd > self.cash_available:
            return False, f"Insufficient cash: ${size_usd:.2f} > ${self.cash_available:.2f}"
        
        return True, "OK"


class SourceTier(str, Enum):
    """Quality tier of information source."""
    TIER1 = "tier1"  # Reuters, AP, official sources
    TIER2 = "tier2"  # Major news outlets
    TIER3 = "tier3"  # Blogs, forums, social media
    NONE = "none"    # No sources found


class Source(BaseModel):
    """A source from research."""
    url: str
    title: str
    snippet: str
    tier: SourceTier = SourceTier.TIER3
    published_at: Optional[datetime] = None
    supports_outcome: Optional[Direction] = None  # What direction this source supports


class AlphaOpportunity(BaseModel):
    """A market with significant edge detected."""
    
    market_id: str
    question: str
    category: Optional[str] = None
    slug: str
    
    market_price: float = Field(ge=0, le=1)
    ai_estimate: float = Field(ge=0, le=1)
    edge_pct: float = Field(ge=0)
    direction: Direction
    
    volume_24h: float = 0
    liquidity: float = 0
    
    timestamp: datetime = Field(default_factory=utcnow)
    
    def __str__(self) -> str:
        return (
            f"[{self.edge_pct:.1f}% edge] {self.direction.value} @ {self.market_price:.1%} "
            f"(AI: {self.ai_estimate:.1%}) - {self.question[:60]}..."
        )


class Market(BaseModel):
    """Polymarket market data."""
    
    id: str
    question: str
    slug: str
    description: str = ""
    
    outcome_prices: list[float]  # [YES_price, NO_price]
    outcomes: list[str] = ["Yes", "No"]
    
    active: bool = True
    closed: bool = False
    
    volume_24h: float = 0
    liquidity: float = 0
    
    category: Optional[str] = None
    end_date: Optional[datetime] = None
    
    @property
    def yes_price(self) -> float:
        return self.outcome_prices[0] if self.outcome_prices else 0.5
    
    @property
    def no_price(self) -> float:
        return self.outcome_prices[1] if len(self.outcome_prices) > 1 else 1 - self.yes_price


class ScanResult(BaseModel):
    """Results from an alpha scan."""
    
    total_markets_scanned: int
    markets_with_alpha: int
    opportunities: list[AlphaOpportunity]
    
    scan_duration_sec: float
    timestamp: datetime = Field(default_factory=utcnow)
    
    errors: list[str] = []


class SearchResult(BaseModel):
    """A single search result from SearXNG."""
    
    title: str
    url: str
    snippet: str = ""
    source: str = ""
    published_date: Optional[datetime] = None
    
    @property
    def is_recent(self) -> bool:
        """Check if result is from last 7 days."""
        if not self.published_date:
            return False
        from datetime import timedelta
        return (utcnow() - self.published_date) < timedelta(days=7)


class ResearchResult(BaseModel):
    """Deep research validation for an alpha opportunity."""
    
    opportunity: AlphaOpportunity
    
    # Research findings
    research_summary: str
    sources: list[str]  # URLs
    key_facts: list[str]  # Bullet points
    
    # AI analysis post-research
    ai_estimate_pre: float = Field(ge=0, le=1)  # Original from scanner
    ai_estimate_post: float = Field(ge=0, le=1)  # After research
    confidence_delta: float  # How much estimate changed
    
    # Research metadata
    queries_run: int = 0
    results_found: int = 0
    recent_sources: int = 0  # Sources from last 7 days
    
    research_duration_sec: float = 0
    timestamp: datetime = Field(default_factory=utcnow)
    
    @property
    def conviction_strengthened(self) -> bool:
        """Did research strengthen the original alpha signal?"""
        # If AI moved closer to original estimate direction, conviction is stronger
        pre_edge = self.opportunity.ai_estimate - self.opportunity.market_price
        post_edge = self.ai_estimate_post - self.opportunity.market_price
        return (pre_edge > 0 and post_edge > pre_edge) or (pre_edge < 0 and post_edge < pre_edge)
    
    @property
    def edge_pct_post(self) -> float:
        """Edge after research."""
        return abs(self.ai_estimate_post - self.opportunity.market_price) * 100
    
    def __str__(self) -> str:
        delta_sign = "+" if self.confidence_delta > 0 else ""
        return (
            f"[{self.edge_pct_post:.1f}% edge] {self.opportunity.question[:50]}... | "
            f"AI: {self.ai_estimate_pre:.0%}→{self.ai_estimate_post:.0%} ({delta_sign}{self.confidence_delta:.0%}) | "
            f"{self.recent_sources} recent sources"
        )


class ConvictionBreakdown(BaseModel):
    """Detailed breakdown of conviction score factors."""
    
    edge_size: float = Field(ge=0, le=10, description="Score for edge magnitude (25% weight)")
    source_quality: float = Field(ge=0, le=10, description="Score for source tier (20% weight)")
    source_agreement: float = Field(ge=0, le=10, description="Score for source consensus (20% weight)")
    recency: float = Field(ge=0, le=10, description="Score for information freshness (15% weight)")
    ai_confidence_delta: float = Field(ge=0, le=10, description="Score for AI confidence change (10% weight)")
    category_track_record: float = Field(ge=0, le=10, description="Score from historical performance (10% weight)")


class ConvictionScore(BaseModel):
    """Final conviction assessment for a trade opportunity."""
    
    research_result: ResearchResult
    
    # Overall score
    score: float = Field(ge=0, le=10, description="Final conviction score 1-10")
    breakdown: ConvictionBreakdown
    
    # Trading decision
    trade_approved: bool = False
    recommended_position_pct: float = Field(ge=0, le=1, default=0)
    position_tier: str = "none"  # "none", "standard", "large", "max"
    
    # Reasoning
    reasoning: str = ""
    risk_flags: list[str] = []
    
    timestamp: datetime = Field(default_factory=utcnow)
    
    def __str__(self) -> str:
        status = "✅ APPROVED" if self.trade_approved else "❌ REJECTED"
        return (
            f"{status} | Score: {self.score:.1f}/10 | "
            f"Position: {self.recommended_position_pct:.1%} ({self.position_tier}) | "
            f"{self.research_result.opportunity.question[:40]}..."
        )
