"""Risk management for V6 Alpha Hunter."""

from dataclasses import dataclass
from typing import Optional
from .models import Position, PortfolioState, PositionStatus


@dataclass
class RiskConfig:
    """Risk management configuration."""
    
    # Position limits
    max_single_position_pct: float = 0.10    # 10% of portfolio
    max_total_exposure_pct: float = 0.50     # 50% of portfolio
    max_concurrent_positions: int = 10
    
    # Stop loss
    hard_stop_pct: float = -0.20             # -20% = exit all
    trailing_activation_pct: float = 0.10    # Activate trailing after +10%
    trailing_stop_pct: float = 0.10          # Trail at -10% from peak
    
    # Take profit thresholds
    tp1_gain_pct: float = 0.15               # +15% = sell 25%
    tp2_gain_pct: float = 0.25               # +25% = sell another 25%
    tp3_gain_pct: float = 0.40               # +40% = sell another 25%
    tp_sell_pct: float = 0.25                # Sell 25% at each level
    
    # Scale-in
    tier_pcts: tuple[float, ...] = (0.33, 0.33, 0.34)  # 3 tiers
    min_hours_between_tiers: float = 4.0


class RiskManager:
    """Enforces risk limits and calculates position sizing."""
    
    def __init__(self, config: Optional[RiskConfig] = None):
        self.config = config or RiskConfig()
    
    # ─────────────────────────────────────────────────────────────
    # Position Sizing
    # ─────────────────────────────────────────────────────────────
    
    def calculate_position_size(
        self,
        portfolio: PortfolioState,
        edge_pct: float,
        conviction: int = 8,
        kelly_fraction: float = 0.5
    ) -> float:
        """
        Calculate position size using fractional Kelly criterion.
        
        Kelly formula: f* = (p * b - q) / b
        Where: p = probability of winning, b = odds, q = 1-p
        
        We use half-Kelly for safety.
        """
        # Convert edge to win probability (edge_pct is the advantage)
        # Assuming ~1:1 odds on Polymarket
        win_prob = 0.5 + (edge_pct / 2)
        win_prob = min(0.95, max(0.05, win_prob))  # Clamp
        
        # Odds (assuming buying at current price, winning pays $1)
        # Simplified: assume b = 1 (even money)
        b = 1.0
        q = 1 - win_prob
        
        # Kelly fraction
        kelly = (win_prob * b - q) / b
        kelly = max(0, kelly)  # No negative sizing
        
        # Apply fraction and conviction scaling
        conviction_scale = conviction / 10  # 8/10 = 0.8x
        adjusted_kelly = kelly * kelly_fraction * conviction_scale
        
        # Calculate dollar amount
        raw_size = portfolio.total_bankroll * adjusted_kelly
        
        # Apply limits
        max_size = portfolio.total_bankroll * self.config.max_single_position_pct
        size = min(raw_size, max_size, portfolio.cash_available)
        
        return round(size, 2)
    
    def tier_size(self, full_size: float, tier: int) -> float:
        """Get the dollar amount for a specific scale-in tier."""
        if tier < 1 or tier > len(self.config.tier_pcts):
            return 0
        return full_size * self.config.tier_pcts[tier - 1]
    
    # ─────────────────────────────────────────────────────────────
    # Risk Checks
    # ─────────────────────────────────────────────────────────────
    
    def check_can_open(self, portfolio: PortfolioState, size_usd: float) -> tuple[bool, str]:
        """Check if a new position can be opened."""
        return portfolio.can_open_position(
            size_usd,
            self.config.max_single_position_pct,
            self.config.max_total_exposure_pct,
            self.config.max_concurrent_positions
        )
    
    def check_can_scale_in(
        self,
        position: Position,
        portfolio: PortfolioState
    ) -> tuple[bool, str]:
        """Check if we can add to an existing position."""
        if position.status not in (PositionStatus.PENDING, PositionStatus.SCALING_IN):
            return False, f"Cannot scale into {position.status.value} position"
        
        if position.tier >= 3:
            return False, "Already at max tier (3)"
        
        if not position.can_add_tier(self.config.min_hours_between_tiers):
            return False, f"Must wait {self.config.min_hours_between_tiers}h between tiers"
        
        next_tier = position.tier + 1
        tier_amount = self.tier_size(position.target_size_usd, next_tier)
        
        # Check portfolio limits
        new_exposure = portfolio.total_exposure + tier_amount
        new_exposure_pct = new_exposure / portfolio.total_bankroll if portfolio.total_bankroll > 0 else 1
        
        if new_exposure_pct > self.config.max_total_exposure_pct:
            return False, f"Would exceed max exposure: {new_exposure_pct:.1%}"
        
        if tier_amount > portfolio.cash_available:
            return False, f"Insufficient cash for tier {next_tier}"
        
        return True, "OK"
    
    # ─────────────────────────────────────────────────────────────
    # Stop Loss Logic
    # ─────────────────────────────────────────────────────────────
    
    def should_stop_loss(self, position: Position) -> tuple[bool, str]:
        """
        Check if position should be stopped out.
        Returns (should_stop, reason).
        """
        if position.is_high_conviction:
            return False, "High conviction - no stop loss"
        
        if position.status in (PositionStatus.STOPPED, PositionStatus.CLOSED, PositionStatus.RESOLVED):
            return False, "Already closed"
        
        pnl_pct = position.unrealized_pnl_pct
        
        # Hard stop at -20%
        if pnl_pct <= self.config.hard_stop_pct:
            return True, f"Hard stop hit: {pnl_pct:.1%} <= {self.config.hard_stop_pct:.0%}"
        
        # Trailing stop (only after +10% gain)
        if position.peak_price > 0 and position.avg_entry_price > 0:
            peak_gain = (position.peak_price - position.avg_entry_price) / position.avg_entry_price
            
            if peak_gain >= self.config.trailing_activation_pct:
                # Trailing stop is active
                current_from_peak = (position.current_price - position.peak_price) / position.peak_price
                
                if current_from_peak <= -self.config.trailing_stop_pct:
                    return True, f"Trailing stop: {current_from_peak:.1%} from peak"
        
        return False, "OK"
    
    # ─────────────────────────────────────────────────────────────
    # Take Profit Logic
    # ─────────────────────────────────────────────────────────────
    
    def check_take_profit(self, position: Position) -> tuple[bool, float, str]:
        """
        Check if position should take profit.
        Returns (should_take_profit, sell_pct, reason).
        """
        if position.status in (PositionStatus.STOPPED, PositionStatus.CLOSED, PositionStatus.RESOLVED):
            return False, 0, "Already closed"
        
        pnl_pct = position.unrealized_pnl_pct
        
        from .models import TakeProfitLevel
        
        # Check TP levels in order
        if position.tp_level == TakeProfitLevel.NONE and pnl_pct >= self.config.tp1_gain_pct:
            return True, self.config.tp_sell_pct, f"TP1: +{pnl_pct:.1%} >= +{self.config.tp1_gain_pct:.0%}"
        
        if position.tp_level == TakeProfitLevel.TP1 and pnl_pct >= self.config.tp2_gain_pct:
            return True, self.config.tp_sell_pct, f"TP2: +{pnl_pct:.1%} >= +{self.config.tp2_gain_pct:.0%}"
        
        if position.tp_level == TakeProfitLevel.TP2 and pnl_pct >= self.config.tp3_gain_pct:
            return True, self.config.tp_sell_pct, f"TP3: +{pnl_pct:.1%} >= +{self.config.tp3_gain_pct:.0%}"
        
        return False, 0, "No TP triggered"
    
    # ─────────────────────────────────────────────────────────────
    # Portfolio Risk Metrics
    # ─────────────────────────────────────────────────────────────
    
    def portfolio_risk_report(self, portfolio: PortfolioState, positions: list[Position]) -> dict:
        """Generate a risk report for the portfolio."""
        active_positions = [p for p in positions if p.status not in 
                          (PositionStatus.CLOSED, PositionStatus.RESOLVED, PositionStatus.STOPPED)]
        
        sizes = [p.current_size_usd for p in active_positions]
        
        return {
            "total_bankroll": portfolio.total_bankroll,
            "cash_available": portfolio.cash_available,
            "total_exposure": portfolio.total_exposure,
            "exposure_pct": portfolio.exposure_pct,
            "position_count": len(active_positions),
            "max_positions": self.config.max_concurrent_positions,
            "largest_position": max(sizes) if sizes else 0,
            "largest_position_pct": max(sizes) / portfolio.total_bankroll if sizes and portfolio.total_bankroll > 0 else 0,
            "avg_position_size": sum(sizes) / len(sizes) if sizes else 0,
            "unrealized_pnl": sum(p.unrealized_pnl for p in active_positions),
            "realized_pnl": sum(p.realized_pnl for p in positions),
            "capacity_remaining": (self.config.max_total_exposure_pct * portfolio.total_bankroll) - portfolio.total_exposure,
            "positions_available": self.config.max_concurrent_positions - len(active_positions),
        }
