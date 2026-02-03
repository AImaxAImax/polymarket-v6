"""V6 Alpha Hunter configuration."""

from dataclasses import dataclass


@dataclass
class V6Config:
    """Configuration for the Alpha Scanner and trading system."""
    
    # === Alpha Scanner ===
    alpha_threshold: float = 0.20  # 20% edge minimum
    batch_size: int = 20
    ollama_delay: float = 0.5  # seconds between calls
    ollama_timeout: int = 30  # seconds per request
    log_interval: int = 50  # log progress every N markets
    
    # === Alpha Calibration (NEW - fixes hallucination) ===
    alpha_min_edge: float = 0.05           # 5% minimum edge to flag
    alpha_max_edge: float = 0.50           # 50% max - cap hallucinations
    alpha_extreme_threshold: float = 0.05  # Markets <5% need higher confidence
    alpha_extreme_min_edge: float = 0.15   # Extreme markets need 15%+ edge
    alpha_require_reasoning: bool = True   # Force LLM to explain disagreement
    
    # === API Endpoints ===
    polymarket_api: str = "https://gamma-api.polymarket.com"
    ollama_url: str = "http://100.112.76.34:11434"
    ollama_model: str = "qwen2.5:32b"
    searxng_url: str = "http://100.112.76.34:8888"
    
    # === Trading Thresholds ===
    min_conviction: int = 8  # 8/10 required to trade
    min_liquidity: float = 1000  # $1k minimum liquidity
    min_volume_24h: float = 500  # $500 minimum daily volume
    
    # === Position Sizing ===
    base_position_pct: float = 0.05  # 5% of bankroll
    max_position_pct: float = 0.10  # 10% max
    kelly_fraction: float = 0.5  # Half-Kelly
    
    # === Risk Management ===
    stop_loss_pct: float = 0.15  # -15% hard stop
    trailing_stop_pct: float = 0.10  # -10% trailing after +10%
    take_profit_first: float = 0.25  # +25% take 50%
    
    # === Scale-in Tiers ===
    scale_tiers: tuple = (0.33, 0.66, 1.0)


# Default config instance
config = V6Config()
