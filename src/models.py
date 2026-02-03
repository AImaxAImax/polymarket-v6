"""Data models for Polymarket V6."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List


@dataclass
class Market:
    """Represents a Polymarket market."""
    id: str
    question: str
    description: Optional[str] = None
    category: Optional[str] = None
    end_date: Optional[str] = None
    
    # Prices
    yes_price: Optional[float] = None
    no_price: Optional[float] = None
    
    # Metrics
    volume: float = 0.0
    liquidity: float = 0.0
    
    # Status
    status: str = "active"
    first_seen_at: Optional[str] = None
    last_updated_at: Optional[str] = None
    resolved_at: Optional[str] = None
    
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
class ResearchResult:
    """Research results for a market."""
    market_id: str
    news_results: List[dict] = field(default_factory=list)
    expert_results: List[dict] = field(default_factory=list)
    source_results: List[dict] = field(default_factory=list)
    summary: str = ""
    researched_at: Optional[str] = None
    
    def compile_summary(self) -> str:
        """Compile all results into a summary string."""
        parts = []
        
        if self.news_results:
            parts.append("=== Recent News ===")
            for r in self.news_results[:5]:
                parts.append(f"- {r.get('title', 'No title')}")
                if r.get('content'):
                    parts.append(f"  {r['content'][:200]}...")
        
        if self.expert_results:
            parts.append("\n=== Expert Analysis ===")
            for r in self.expert_results[:3]:
                parts.append(f"- {r.get('title', 'No title')}")
                if r.get('content'):
                    parts.append(f"  {r['content'][:200]}...")
        
        if self.source_results:
            parts.append("\n=== Resolution Sources ===")
            for r in self.source_results[:3]:
                parts.append(f"- {r.get('title', 'No title')} ({r.get('url', '')})")
        
        self.summary = "\n".join(parts) if parts else "No research data available."
        return self.summary


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
