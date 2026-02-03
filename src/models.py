"""Data models for Polymarket V6."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List


def utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


class Direction(Enum):
    """Trade direction."""

    YES = "YES"
    NO = "NO"


class SourceTier(Enum):
    """Source quality tiers."""

    TIER1 = "tier1"
    TIER2 = "tier2"
    TIER3 = "tier3"


class PositionStatus(Enum):
    """Position lifecycle status."""

    PENDING = "PENDING"
    SCALING_IN = "SCALING_IN"
    ACTIVE = "ACTIVE"
    SCALING_OUT = "SCALING_OUT"
    STOPPED = "STOPPED"
    CLOSED = "CLOSED"
    RESOLVED = "RESOLVED"


class TakeProfitLevel(Enum):
    """Take-profit stages."""

    NONE = "NONE"
    TP1 = "TP1"
    TP2 = "TP2"
    TP3 = "TP3"


@dataclass
class Market:
    """Represents a Polymarket market."""

    id: str
    question: str
    description: Optional[str] = None
    category: Optional[str] = None
    end_date: Optional[str] = None
    slug: Optional[str] = None

    # Pricing (scanner pipeline)
    yes_price: Optional[float] = None
    no_price: Optional[float] = None

    # Pricing (alpha scanner pipeline)
    outcome_prices: Optional[List[float]] = None
    outcomes: Optional[List[str]] = None

    # Metrics
    volume: float = 0.0
    liquidity: float = 0.0
    volume_24h: float = 0.0

    # Status (scanner pipeline)
    status: str = "active"
    first_seen_at: Optional[str] = None
    last_updated_at: Optional[str] = None
    resolved_at: Optional[str] = None

    # Alpha scanner flags
    active: Optional[bool] = None
    closed: Optional[bool] = None

    # Research
    researched_at: Optional[str] = None
    research_summary: Optional[str] = None

    # AI Analysis
    ai_probability: Optional[float] = None
    ai_confidence: Optional[float] = None
    ai_reasoning: Optional[str] = None
    analyzed_at: Optional[str] = None

    # Signals
    edge: Optional[float] = None
    signal: Optional[str] = None
    recommended_size: Optional[float] = None

    def __post_init__(self) -> None:
        if self.outcome_prices and (self.yes_price is None or self.no_price is None):
            if len(self.outcome_prices) >= 2:
                self.yes_price = self.outcome_prices[0]
                self.no_price = self.outcome_prices[1]

    def to_dict(self) -> dict:
        """Convert to dictionary for database operations."""
        return {
            "id": self.id,
            "question": self.question,
            "description": self.description,
            "category": self.category,
            "end_date": self.end_date,
            "yes_price": self.yes_price,
            "no_price": self.no_price,
            "volume": self.volume,
            "liquidity": self.liquidity,
            "status": self.status,
            "first_seen_at": self.first_seen_at,
            "last_updated_at": self.last_updated_at,
            "resolved_at": self.resolved_at,
            "researched_at": self.researched_at,
            "research_summary": self.research_summary,
            "ai_probability": self.ai_probability,
            "ai_confidence": self.ai_confidence,
            "ai_reasoning": self.ai_reasoning,
            "analyzed_at": self.analyzed_at,
            "edge": self.edge,
            "signal": self.signal,
            "recommended_size": self.recommended_size,
        }


@dataclass
class AlphaOpportunity:
    """Alpha opportunity found by the scanner."""

    market_id: str
    question: str
    slug: str
    market_price: float
    ai_estimate: float
    edge_pct: float
    direction: Direction
    category: Optional[str] = None
    volume_24h: float = 0.0
    liquidity: float = 0.0
    reasoning: Optional[str] = None

    def __str__(self) -> str:
        return (
            f"{self.direction.value} {self.market_id} "
            f"{self.edge_pct:.1f}% edge @ {self.market_price:.1%}"
        )


@dataclass
class ScanResult:
    """Scan result summary."""

    total_markets_scanned: int
    markets_with_alpha: int
    opportunities: List[AlphaOpportunity]
    scan_duration_sec: float
    errors: List[str] = field(default_factory=list)


@dataclass
class SearchResult:
    """Single search result."""

    title: str
    url: str
    snippet: str
    source: str
    published_date: Optional[datetime] = None

    @property
    def is_recent(self) -> bool:
        if not self.published_date:
            return False
        return (utcnow() - self.published_date).days <= 7


@dataclass
class ResearchResult:
    """Research results for a market."""

    # Scanner pipeline fields
    market_id: Optional[str] = None
    news_results: List[dict] = field(default_factory=list)
    expert_results: List[dict] = field(default_factory=list)
    source_results: List[dict] = field(default_factory=list)
    summary: str = ""
    researched_at: Optional[str] = None

    # Alpha Hunter pipeline fields
    opportunity: Optional[AlphaOpportunity] = None
    research_summary: str = ""
    sources: List[str] = field(default_factory=list)
    key_facts: List[str] = field(default_factory=list)
    ai_estimate_pre: float = 0.0
    ai_estimate_post: float = 0.0
    confidence_delta: float = 0.0
    queries_run: int = 0
    results_found: int = 0
    recent_sources: int = 0
    research_duration_sec: float = 0.0

    def compile_summary(self) -> str:
        """Compile all results into a summary string."""
        parts = []

        if self.news_results:
            parts.append("=== Recent News ===")
            for r in self.news_results[:5]:
                parts.append(f"- {r.get('title', 'No title')}")
                if r.get("content"):
                    parts.append(f"  {r['content'][:200]}...")

        if self.expert_results:
            parts.append("\n=== Expert Analysis ===")
            for r in self.expert_results[:3]:
                parts.append(f"- {r.get('title', 'No title')}")
                if r.get("content"):
                    parts.append(f"  {r['content'][:200]}...")

        if self.source_results:
            parts.append("\n=== Resolution Sources ===")
            for r in self.source_results[:3]:
                parts.append(f"- {r.get('title', 'No title')} ({r.get('url', '')})")

        self.summary = "\n".join(parts) if parts else "No research data available."
        self.research_summary = self.summary
        return self.summary

    @property
    def edge_pct_post(self) -> float:
        if not self.opportunity:
            return 0.0
        return abs(self.ai_estimate_post - self.opportunity.market_price) * 100

    @property
    def conviction_strengthened(self) -> bool:
        return self.confidence_delta > 0


@dataclass
class Signal:
    """Trading signal for a market."""

    market_id: str
    signal: str  # BUY, SKIP, AVOID
    edge: float
    confidence: float
    recommended_size: float
    reasoning: str

    @property
    def is_opportunity(self) -> bool:
        return self.signal == "BUY" and self.edge > 0.05 and self.confidence > 0.6


@dataclass
class ConvictionBreakdown:
    """Breakdown of conviction scoring factors."""

    edge_size: float
    source_quality: float
    source_agreement: float
    recency: float
    ai_confidence_delta: float
    category_track_record: float


@dataclass
class ConvictionScore:
    """Conviction score with decision."""

    research_result: ResearchResult
    score: float
    breakdown: ConvictionBreakdown
    trade_approved: bool
    recommended_position_pct: float
    position_tier: str
    reasoning: str
    risk_flags: List[str] = field(default_factory=list)


@dataclass
class Position:
    """Trading position."""

    market_id: str
    question: str
    direction: Direction
    tier: int
    target_size_usd: float
    current_size_usd: float
    avg_entry_price: float
    current_price: float
    peak_price: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    status: PositionStatus = PositionStatus.PENDING
    tp_level: TakeProfitLevel = TakeProfitLevel.NONE
    is_high_conviction: bool = False
    created_at: datetime = field(default_factory=utcnow)
    last_tier_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    notes: str = ""
    id: Optional[int] = None

    def can_add_tier(self, min_hours_between_tiers: float) -> bool:
        if not self.last_tier_at:
            return True
        delta = utcnow() - self.last_tier_at
        return delta.total_seconds() >= min_hours_between_tiers * 3600


@dataclass
class PortfolioState:
    """Portfolio summary stats."""

    total_bankroll: float
    cash_available: float
    total_exposure: float
    exposure_pct: float
    position_count: int
    unrealized_pnl: float
    realized_pnl: float
    largest_position_pct: float
    avg_position_size: float

    def can_open_position(
        self,
        size_usd: float,
        max_single_position_pct: float,
        max_total_exposure_pct: float,
        max_concurrent_positions: int,
    ) -> tuple[bool, str]:
        """Check whether a new position can be opened."""
        if self.position_count >= max_concurrent_positions:
            return False, "Max positions reached"

        if size_usd > self.cash_available:
            return False, "Insufficient cash"

        if self.total_bankroll <= 0:
            return False, "Invalid bankroll"

        if size_usd / self.total_bankroll > max_single_position_pct:
            return False, "Position size exceeds max single position limit"

        new_exposure = self.total_exposure + size_usd
        if new_exposure / self.total_bankroll > max_total_exposure_pct:
            return False, "Total exposure would exceed limit"

        return True, "OK"
