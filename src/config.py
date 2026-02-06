"""V6 Alpha Hunter configuration.

Loads settings from environment variables (via .env file) with sensible defaults.
All network endpoints default to localhost — override via .env for Tailscale/remote hosts.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

# Load .env if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_float(key: str, default: float) -> float:
    return float(os.environ.get(key, str(default)))


def _env_int(key: str, default: int) -> int:
    return int(os.environ.get(key, str(default)))


def _env_bool(key: str, default: bool) -> bool:
    val = os.environ.get(key, str(default)).lower()
    return val in ("true", "1", "yes")


@dataclass
class V6Config:
    """Configuration for the Alpha Scanner and trading system."""

    # === API Endpoints (override via .env) ===
    polymarket_api: str = field(
        default_factory=lambda: _env("POLYMARKET_API", "https://gamma-api.polymarket.com")
    )
    ollama_url: str = field(
        default_factory=lambda: _env("OLLAMA_URL", "http://localhost:11434")
    )
    ollama_model: str = field(
        default_factory=lambda: _env("OLLAMA_MODEL", "qwen2.5:32b")
    )
    searxng_url: str = field(
        default_factory=lambda: _env("SEARXNG_URL", "http://localhost:8888")
    )

    # === Alpha Scanner ===
    alpha_threshold: float = 0.20  # 20% edge minimum
    batch_size: int = 20
    ollama_delay: float = 0.5   # seconds between calls
    ollama_timeout: int = 30    # seconds per request
    log_interval: int = 50      # log progress every N markets

    # === Alpha Calibration (fixes LLM hallucination) ===
    alpha_min_edge: float = 0.05           # 5% minimum edge to flag
    alpha_max_edge: float = 0.50           # 50% max — cap hallucinations
    alpha_extreme_threshold: float = 0.05  # Markets <5% need higher confidence
    alpha_extreme_min_edge: float = 0.15   # Extreme markets need 15%+ edge
    alpha_require_reasoning: bool = True   # Force LLM to explain disagreement

    # === Trading Thresholds ===
    min_conviction: int = 8      # 8/10 required to trade
    min_liquidity: float = 1000  # $1k minimum liquidity
    min_volume_24h: float = 500  # $500 minimum daily volume

    # === Position Sizing ===
    base_position_pct: float = 0.05  # 5% of bankroll
    max_position_pct: float = 0.10   # 10% max
    kelly_fraction: float = 0.5      # Half-Kelly

    # === Risk Management ===
    stop_loss_pct: float = 0.15       # -15% hard stop
    trailing_stop_pct: float = 0.10   # -10% trailing after +10%
    take_profit_first: float = 0.25   # +25% take 50%

    # === Scale-in Tiers ===
    scale_tiers: tuple = (0.33, 0.66, 1.0)

    # === HTTP Resilience ===
    http_max_retries: int = 3
    http_retry_backoff: float = 1.0  # base seconds, doubles each retry


# Default config instance
config = V6Config()
