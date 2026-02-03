"""Bot configuration for V6 Alpha Hunter."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class BotConfig:
    """Main bot orchestrator configuration."""
    
    # === Scanning ===
    scan_interval_hours: float = 1.0          # Time between full scans
    min_edge_pct: float = 20.0                # Minimum edge % to consider
    max_markets_per_scan: Optional[int] = None  # None = ALL markets
    top_opportunities_to_research: int = 50   # Deep research top N
    
    # === Trading ===
    paper_trading: bool = True                # CRITICAL: Default to paper
    max_new_positions_per_cycle: int = 3      # Max positions per scan cycle
    min_conviction_score: float = 8.0         # Minimum to approve trade
    
    # === Capital ===
    initial_capital: float = 10000.0          # Starting bankroll USD
    position_size_pct: float = 0.05           # 5% base position size
    
    # === Risk ===
    max_concurrent_positions: int = 10
    max_exposure_pct: float = 0.50            # 50% max portfolio exposure
    
    # === Paths ===
    data_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "data")
    positions_db: str = "positions.db"
    learning_db: str = "learning.db"
    
    # === Dashboard ===
    dashboard_port: int = 8898
    dashboard_host: str = "0.0.0.0"
    
    # === Logging ===
    log_level: str = "INFO"
    log_file: Optional[str] = None            # None = stdout only
    
    @property
    def positions_db_path(self) -> Path:
        return self.data_dir / self.positions_db
    
    @property
    def learning_db_path(self) -> Path:
        return self.data_dir / self.learning_db
    
    def ensure_data_dir(self):
        """Create data directory if it doesn't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)


# Default config
bot_config = BotConfig()


# Quick config presets
def get_paper_config() -> BotConfig:
    """Get paper trading config (safe defaults)."""
    return BotConfig(
        paper_trading=True,
        initial_capital=10000.0,
        max_new_positions_per_cycle=3,
    )


def get_live_config(capital: float = 10000.0) -> BotConfig:
    """Get live trading config (requires confirmation)."""
    return BotConfig(
        paper_trading=False,
        initial_capital=capital,
        max_new_positions_per_cycle=2,  # More conservative
        position_size_pct=0.03,         # Smaller positions
        max_exposure_pct=0.40,          # Lower exposure
    )


def get_scan_only_config() -> BotConfig:
    """Get config for scan-only mode (no trading)."""
    return BotConfig(
        paper_trading=True,
        max_new_positions_per_cycle=0,  # No trading
        scan_interval_hours=0,          # Single scan
    )
