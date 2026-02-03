"""Polymarket V6 Alpha Hunter."""

from .alpha_scanner import AlphaScanner, run_scan
from .config import V6Config, config
from .bot_config import BotConfig, bot_config, get_paper_config, get_live_config
from .conviction_engine import ConvictionEngine, create_engine, score_opportunity
from .deep_research import DeepResearcher, run_research
from .models import (
    AlphaOpportunity,
    ConvictionBreakdown,
    ConvictionScore,
    Direction,
    Market,
    Position,
    PositionStatus,
    PortfolioState,
    ResearchResult,
    ScanResult,
    Source,
    SourceTier,
    TakeProfitLevel,
)
from .risk_manager import RiskManager, RiskConfig
from .position_manager import PositionManager
from .learning_loop import LearningLoop, TradeOutcome, CategoryStats, create_mock_trades
from .pattern_analyzer import PatternAnalyzer, LearningReport, WinningPattern
from .bot import AlphaHunterBot

__all__ = [
    # Main Bot
    "AlphaHunterBot",
    "BotConfig",
    "bot_config",
    "get_paper_config",
    "get_live_config",
    # Scanner
    "AlphaScanner",
    "run_scan",
    # Research
    "DeepResearcher",
    "run_research",
    # Config
    "V6Config",
    "config",
    # Conviction
    "ConvictionEngine",
    "create_engine",
    "score_opportunity",
    # Models
    "AlphaOpportunity",
    "ConvictionBreakdown",
    "ConvictionScore",
    "Direction",
    "Market",
    "Position",
    "PositionStatus",
    "PortfolioState",
    "ResearchResult",
    "ScanResult",
    "Source",
    "SourceTier",
    "TakeProfitLevel",
    # Risk & Position Management
    "RiskManager",
    "RiskConfig",
    "PositionManager",
    # Learning Loop
    "LearningLoop",
    "TradeOutcome",
    "CategoryStats",
    "create_mock_trades",
    # Pattern Analyzer
    "PatternAnalyzer",
    "LearningReport",
    "WinningPattern",
]
