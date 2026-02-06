"""Test Position Manager with full simulation."""

import sys
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to path for proper imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import AlphaOpportunity, Direction, PositionStatus, TakeProfitLevel
from src.risk_manager import RiskManager, RiskConfig
from src.position_manager import PositionManager


def test_full_position_lifecycle():
    """
    Simulate a complete position lifecycle:
    1. Open position (Tier 1)
    2. Scale in (Tier 2 & 3)
    3. Hit take profit levels
    4. Show final P&L
    """
    print("\n" + "═" * 70)
    print("🧪 POSITION MANAGER SIMULATION")
    print("═" * 70)
    
    # Use temp database
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_positions.db")
        
        # Initialize with $10,000 bankroll
        pm = PositionManager(
            db_path=db_path,
            initial_bankroll=10000.0
        )
        
        # Create a mock alpha opportunity
        opportunity = AlphaOpportunity(
            market_id="test-market-123",
            question="Will Bitcoin reach $100k by end of 2024?",
            slug="btc-100k-2024",
            market_price=0.35,
            ai_estimate=0.55,
            edge_pct=20.0,
            direction=Direction.YES,
            volume_24h=50000,
            liquidity=25000
        )
        
        print(f"\n📈 Opportunity: {opportunity.question}")
        print(f"   Market: {opportunity.market_price:.0%} | AI: {opportunity.ai_estimate:.0%} | Edge: {opportunity.edge_pct:.0f}%")
        
        # Calculate position size (~$500 for this edge/conviction)
        portfolio = pm.get_portfolio_state()
        target_size = pm.risk.calculate_position_size(portfolio, opportunity.edge_pct / 100, conviction=8)
        print(f"\n💰 Target position size: ${target_size:.2f} (calculated via Kelly)")
        
        # ─────────────────────────────────────────────────────────────
        # STEP 1: Open Position (Tier 1 = 33%)
        # ─────────────────────────────────────────────────────────────
        print("\n" + "─" * 70)
        print("STEP 1: OPEN POSITION (Tier 1)")
        print("─" * 70)
        
        position, msg = pm.open_position(
            opportunity=opportunity,
            target_size_usd=target_size,
            entry_price=0.35
        )
        print(f"   {msg}")
        print(f"   Position ID: {position.id}")
        print(f"   Size: ${position.current_size_usd:.2f} / ${position.target_size_usd:.2f}")
        print(f"   Status: {position.status.value}")
        
        # ─────────────────────────────────────────────────────────────
        # STEP 2: Price moves up, scale in Tier 2
        # ─────────────────────────────────────────────────────────────
        print("\n" + "─" * 70)
        print("STEP 2: SCALE IN (Tier 2) - Price moved to 0.40")
        print("─" * 70)
        
        # Simulate time passing (need 4 hours between tiers)
        position.last_tier_at = datetime.now(timezone.utc) - timedelta(hours=5)
        pm._save_position(position)
        
        position, msg = pm.scale_in(position, current_price=0.40, thesis_confirmed=True)
        print(f"   {msg}")
        print(f"   Avg Entry: {position.avg_entry_price:.4f}")
        print(f"   Size: ${position.current_size_usd:.2f}")
        
        # ─────────────────────────────────────────────────────────────
        # STEP 3: Continue momentum, scale in Tier 3
        # ─────────────────────────────────────────────────────────────
        print("\n" + "─" * 70)
        print("STEP 3: SCALE IN (Tier 3) - Price at 0.42")
        print("─" * 70)
        
        position.last_tier_at = datetime.now(timezone.utc) - timedelta(hours=5)
        pm._save_position(position)
        
        position, msg = pm.scale_in(position, current_price=0.42, thesis_confirmed=True)
        print(f"   {msg}")
        print(f"   Avg Entry: {position.avg_entry_price:.4f}")
        print(f"   Total Size: ${position.current_size_usd:.2f}")
        print(f"   Status: {position.status.value}")
        
        # ─────────────────────────────────────────────────────────────
        # STEP 4: Price pumps - Take Profit 1 (+15%)
        # ─────────────────────────────────────────────────────────────
        print("\n" + "─" * 70)
        print("STEP 4: TAKE PROFIT 1 - Price at 0.46 (+18% from avg entry)")
        print("─" * 70)
        
        position, msg = pm.take_profit(position, current_price=0.46)
        print(f"   {msg}")
        print(f"   Remaining Size: ${position.current_size_usd:.2f}")
        print(f"   Realized P&L: ${position.realized_pnl:.2f}")
        print(f"   TP Level: {position.tp_level.value}")
        
        # ─────────────────────────────────────────────────────────────
        # STEP 5: Continue pumping - Take Profit 2 (+25%)
        # ─────────────────────────────────────────────────────────────
        print("\n" + "─" * 70)
        print("STEP 5: TAKE PROFIT 2 - Price at 0.50 (+29% from avg entry)")
        print("─" * 70)
        
        position, msg = pm.take_profit(position, current_price=0.50)
        print(f"   {msg}")
        print(f"   Remaining Size: ${position.current_size_usd:.2f}")
        print(f"   Realized P&L: ${position.realized_pnl:.2f}")
        print(f"   TP Level: {position.tp_level.value}")
        
        # ─────────────────────────────────────────────────────────────
        # STEP 6: Moon! Take Profit 3 (+40%)
        # ─────────────────────────────────────────────────────────────
        print("\n" + "─" * 70)
        print("STEP 6: TAKE PROFIT 3 - Price at 0.56 (+45% from avg entry)")
        print("─" * 70)
        
        position, msg = pm.take_profit(position, current_price=0.56)
        print(f"   {msg}")
        print(f"   Remaining Size: ${position.current_size_usd:.2f} (25% rides to resolution)")
        print(f"   Realized P&L: ${position.realized_pnl:.2f}")
        print(f"   TP Level: {position.tp_level.value}")
        
        # ─────────────────────────────────────────────────────────────
        # STEP 7: Market resolves YES at $1.00!
        # ─────────────────────────────────────────────────────────────
        print("\n" + "─" * 70)
        print("STEP 7: MARKET RESOLVED - YES wins! Price = 1.00")
        print("─" * 70)
        
        position, msg = pm.mark_resolved(position, outcome_price=1.00)
        print(f"   {msg}")
        print(f"   Status: {position.status.value}")
        
        # ─────────────────────────────────────────────────────────────
        # FINAL SUMMARY
        # ─────────────────────────────────────────────────────────────
        print("\n" + "═" * 70)
        print("📊 FINAL P&L BREAKDOWN")
        print("═" * 70)
        
        history = pm.position_history(position.id)
        print("\n📜 Trade History:")
        for h in history:
            pnl_str = f"P&L: ${h['pnl']:+.2f}" if h['pnl'] else ""
            print(f"   [{h['timestamp'][:19]}] {h['action']}: ${h['amount_usd']:.2f} @ {h['price']:.4f} {pnl_str}")
        
        portfolio = pm.get_portfolio_state()
        print(f"\n💎 Total Realized P&L: ${position.realized_pnl:.2f}")
        print(f"📈 Return on Investment: {(position.realized_pnl / target_size * 100):.1f}%")
        print(f"💰 New Bankroll: ${portfolio.total_bankroll:,.2f}")
        
        # ─────────────────────────────────────────────────────────────
        print("\n" + pm.positions_summary())
        
        return True


def test_stop_loss():
    """Test stop loss triggers correctly."""
    print("\n" + "═" * 70)
    print("🧪 STOP LOSS SIMULATION")
    print("═" * 70)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_positions.db")
        pm = PositionManager(db_path=db_path, initial_bankroll=10000.0)
        
        opportunity = AlphaOpportunity(
            market_id="stop-loss-test",
            question="Will this trade get stopped out?",
            slug="stop-test",
            market_price=0.50,
            ai_estimate=0.70,
            edge_pct=20.0,
            direction=Direction.YES,
        )
        
        position, msg = pm.open_position(opportunity, target_size_usd=500, entry_price=0.50)
        print(f"\n   Opened: {msg}")
        
        # Price drops -25% (below -20% hard stop)
        print("\n   Price drops to 0.375 (-25%)...")
        position, msg = pm.stop_loss(position, current_price=0.375)
        print(f"   Result: {msg}")
        
        assert position.status == PositionStatus.STOPPED
        print(f"\n   ✅ Stop loss worked! Status: {position.status.value}")
        return True


def test_trailing_stop():
    """Test trailing stop activates and triggers correctly."""
    print("\n" + "═" * 70)
    print("🧪 TRAILING STOP SIMULATION")
    print("═" * 70)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_positions.db")
        pm = PositionManager(db_path=db_path, initial_bankroll=10000.0)
        
        opportunity = AlphaOpportunity(
            market_id="trailing-stop-test",
            question="Will trailing stop work?",
            slug="trail-test",
            market_price=0.50,
            ai_estimate=0.70,
            edge_pct=20.0,
            direction=Direction.YES,
        )
        
        position, msg = pm.open_position(opportunity, target_size_usd=500, entry_price=0.50)
        print(f"\n   Opened @ 0.50")
        
        # Price goes up +15% (activates trailing at +10%)
        pm.update_price(position, 0.575)
        print(f"   Price rises to 0.575 (+15%) - Trailing stop now active")
        print(f"   Peak price: {position.peak_price}")
        
        # Price drops but not enough to trigger
        position, msg = pm.stop_loss(position, current_price=0.55)
        print(f"   Price drops to 0.55 (-4.3% from peak): {msg}")
        
        # Price drops -11% from peak (triggers trailing)
        print(f"\n   Price drops to 0.51 (-11% from peak)...")
        position, msg = pm.stop_loss(position, current_price=0.51)
        print(f"   Result: {msg}")
        
        assert position.status == PositionStatus.STOPPED
        print(f"\n   ✅ Trailing stop worked! Realized P&L: ${position.realized_pnl:.2f}")
        return True


def test_risk_limits():
    """Test risk limits are enforced."""
    print("\n" + "═" * 70)
    print("🧪 RISK LIMITS TEST")
    print("═" * 70)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_positions.db")
        pm = PositionManager(db_path=db_path, initial_bankroll=10000.0)
        
        portfolio = pm.get_portfolio_state()
        
        # Try to open position > 10% of portfolio
        can_open, reason = pm.risk.check_can_open(portfolio, 1500)  # 15%
        print(f"\n   Open 15% position: {can_open} - {reason}")
        assert not can_open
        
        # Open max positions (10)
        print("\n   Opening 10 positions of $400 each...")
        for i in range(10):
            opp = AlphaOpportunity(
                market_id=f"market-{i}",
                question=f"Test market {i}",
                slug=f"test-{i}",
                market_price=0.50,
                ai_estimate=0.60,
                edge_pct=10.0,
                direction=Direction.YES,
            )
            pos, msg = pm.open_position(opp, target_size_usd=400, entry_price=0.50)
            # Each tier 1 is 33% = $132
        
        portfolio = pm.get_portfolio_state()
        print(f"   Positions: {portfolio.position_count}")
        print(f"   Exposure: ${portfolio.total_exposure:.2f} ({portfolio.exposure_pct:.1%})")
        
        # Try to open 11th position
        opp = AlphaOpportunity(
            market_id="market-11",
            question="This should fail",
            slug="test-11",
            market_price=0.50,
            ai_estimate=0.60,
            edge_pct=10.0,
            direction=Direction.YES,
        )
        pos, msg = pm.open_position(opp, target_size_usd=400, entry_price=0.50)
        print(f"\n   11th position: {msg}")
        assert "Max positions" in msg
        
        print("\n   ✅ Risk limits enforced correctly!")
        return True


def test_high_conviction_no_stop():
    """Test high conviction positions ignore stop loss."""
    print("\n" + "═" * 70)
    print("🧪 HIGH CONVICTION (NO STOP LOSS) TEST")
    print("═" * 70)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_positions.db")
        pm = PositionManager(db_path=db_path, initial_bankroll=10000.0)
        
        opportunity = AlphaOpportunity(
            market_id="high-conviction-test",
            question="Super high conviction event market",
            slug="high-conv",
            market_price=0.50,
            ai_estimate=0.90,
            edge_pct=40.0,
            direction=Direction.YES,
        )
        
        # Open as high conviction
        position, msg = pm.open_position(
            opportunity, 
            target_size_usd=500, 
            entry_price=0.50,
            is_high_conviction=True
        )
        print(f"\n   Opened high conviction position")
        
        # Price drops -30% (would normally trigger stop)
        position, msg = pm.stop_loss(position, current_price=0.35)
        print(f"   Price drops -30%: {msg}")
        
        assert position.status != PositionStatus.STOPPED
        print(f"   ✅ High conviction position NOT stopped - will ride to resolution")
        return True


if __name__ == "__main__":
    print("\n" + "🚀" * 35)
    print("   POLYMARKET V6 - POSITION MANAGER TESTS")
    print("🚀" * 35)
    
    tests = [
        ("Full Position Lifecycle", test_full_position_lifecycle),
        ("Stop Loss", test_stop_loss),
        ("Trailing Stop", test_trailing_stop),
        ("Risk Limits", test_risk_limits),
        ("High Conviction No Stop", test_high_conviction_no_stop),
    ]
    
    results = []
    for name, test_fn in tests:
        try:
            passed = test_fn()
            results.append((name, passed, None))
        except Exception as e:
            results.append((name, False, str(e)))
    
    print("\n" + "═" * 70)
    print("📋 TEST RESULTS")
    print("═" * 70)
    
    for name, passed, error in results:
        status = "✅ PASS" if passed else f"❌ FAIL: {error}"
        print(f"   {name}: {status}")
    
    all_passed = all(r[1] for r in results)
    print("\n" + ("🎉 All tests passed!" if all_passed else "⚠️ Some tests failed"))
