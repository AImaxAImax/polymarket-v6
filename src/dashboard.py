"""
V6 Alpha Hunter — Status Dashboard

Simple FastAPI dashboard showing:
- Current positions
- Pending opportunities
- Total P&L
- Learning stats

Run: python -m src.dashboard
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from .bot_config import BotConfig, bot_config
from .position_manager import PositionManager
from .learning_loop import LearningLoop
from .risk_manager import RiskConfig

# Initialize FastAPI
app = FastAPI(title="V6 Alpha Hunter", description="Polymarket Trading Bot Dashboard")

# Initialize components (read-only mode)
config = bot_config
position_manager = PositionManager(
    db_path=str(config.positions_db_path),
    risk_config=RiskConfig(),
    initial_bankroll=config.initial_capital,
)
learning_loop = LearningLoop(db_path=config.learning_db_path)


# === HTML Template ===

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>V6 Alpha Hunter</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .gradient-bg { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%); }
        .card { background: rgba(255,255,255,0.05); backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,0.1); }
        .positive { color: #4ade80; }
        .negative { color: #f87171; }
    </style>
</head>
<body class="gradient-bg min-h-screen text-white">
    <div class="container mx-auto px-4 py-8">
        <!-- Header -->
        <div class="flex items-center justify-between mb-8">
            <div>
                <h1 class="text-4xl font-bold">🎯 V6 Alpha Hunter</h1>
                <p class="text-gray-400 mt-1">Polymarket Trading Bot</p>
            </div>
            <div id="mode-badge" class="px-4 py-2 rounded-full text-lg font-semibold">
                <!-- Filled by JS -->
            </div>
        </div>

        <!-- Stats Cards -->
        <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
            <div class="card rounded-xl p-6">
                <div class="text-gray-400 text-sm">Total Bankroll</div>
                <div id="total-bankroll" class="text-3xl font-bold mt-1">$0</div>
            </div>
            <div class="card rounded-xl p-6">
                <div class="text-gray-400 text-sm">Unrealized P&L</div>
                <div id="unrealized-pnl" class="text-3xl font-bold mt-1">$0</div>
            </div>
            <div class="card rounded-xl p-6">
                <div class="text-gray-400 text-sm">Realized P&L</div>
                <div id="realized-pnl" class="text-3xl font-bold mt-1">$0</div>
            </div>
            <div class="card rounded-xl p-6">
                <div class="text-gray-400 text-sm">Positions</div>
                <div id="position-count" class="text-3xl font-bold mt-1">0</div>
            </div>
        </div>

        <!-- Two Column Layout -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
            <!-- Positions -->
            <div class="card rounded-xl p-6">
                <h2 class="text-xl font-bold mb-4">📊 Active Positions</h2>
                <div id="positions-list" class="space-y-4">
                    <!-- Filled by JS -->
                </div>
            </div>

            <!-- Learning Stats -->
            <div class="card rounded-xl p-6">
                <h2 class="text-xl font-bold mb-4">📚 Learning Stats</h2>
                <div id="learning-stats" class="space-y-2">
                    <!-- Filled by JS -->
                </div>
                
                <h3 class="text-lg font-semibold mt-6 mb-3">Recent Trades</h3>
                <div id="recent-trades" class="space-y-2">
                    <!-- Filled by JS -->
                </div>
            </div>
        </div>

        <!-- Exposure Bar -->
        <div class="card rounded-xl p-6 mt-8">
            <div class="flex justify-between mb-2">
                <span class="text-gray-400">Portfolio Exposure</span>
                <span id="exposure-pct" class="font-mono">0%</span>
            </div>
            <div class="w-full bg-gray-700 rounded-full h-4">
                <div id="exposure-bar" class="bg-blue-500 h-4 rounded-full transition-all" style="width: 0%"></div>
            </div>
        </div>

        <!-- Footer -->
        <div class="text-center text-gray-500 text-sm mt-8">
            Last updated: <span id="last-update">-</span> | 
            Auto-refresh every 30 seconds
        </div>
    </div>

    <script>
        async function fetchData() {
            try {
                const resp = await fetch('/api/status');
                const data = await resp.json();
                updateDashboard(data);
            } catch (e) {
                console.error('Failed to fetch data:', e);
            }
        }

        function updateDashboard(data) {
            // Mode badge
            const modeBadge = document.getElementById('mode-badge');
            if (data.mode === 'PAPER') {
                modeBadge.textContent = '📄 PAPER';
                modeBadge.className = 'px-4 py-2 rounded-full text-lg font-semibold bg-yellow-500/20 text-yellow-400';
            } else {
                modeBadge.textContent = '💰 LIVE';
                modeBadge.className = 'px-4 py-2 rounded-full text-lg font-semibold bg-green-500/20 text-green-400';
            }

            // Portfolio stats
            const portfolio = data.portfolio;
            document.getElementById('total-bankroll').textContent = `$${portfolio.total_bankroll.toLocaleString(undefined, {minimumFractionDigits: 2})}`;
            
            const unrealizedEl = document.getElementById('unrealized-pnl');
            unrealizedEl.textContent = `${portfolio.unrealized_pnl >= 0 ? '+' : ''}$${portfolio.unrealized_pnl.toLocaleString(undefined, {minimumFractionDigits: 2})}`;
            unrealizedEl.className = `text-3xl font-bold mt-1 ${portfolio.unrealized_pnl >= 0 ? 'positive' : 'negative'}`;
            
            const realizedEl = document.getElementById('realized-pnl');
            realizedEl.textContent = `${portfolio.realized_pnl >= 0 ? '+' : ''}$${portfolio.realized_pnl.toLocaleString(undefined, {minimumFractionDigits: 2})}`;
            realizedEl.className = `text-3xl font-bold mt-1 ${portfolio.realized_pnl >= 0 ? 'positive' : 'negative'}`;
            
            document.getElementById('position-count').textContent = `${data.positions.length}/10`;

            // Exposure bar
            const exposurePct = (portfolio.exposure_pct * 100).toFixed(1);
            document.getElementById('exposure-pct').textContent = `${exposurePct}%`;
            document.getElementById('exposure-bar').style.width = `${exposurePct}%`;

            // Positions
            const positionsList = document.getElementById('positions-list');
            if (data.positions.length === 0) {
                positionsList.innerHTML = '<p class="text-gray-500">No active positions</p>';
            } else {
                positionsList.innerHTML = data.positions.map(pos => `
                    <div class="bg-white/5 rounded-lg p-4">
                        <div class="flex justify-between items-start">
                            <div>
                                <span class="px-2 py-1 rounded text-xs ${pos.direction === 'YES' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}">${pos.direction}</span>
                                <span class="text-gray-400 text-xs ml-2">Tier ${pos.tier}/3</span>
                            </div>
                            <div class="text-right">
                                <span class="${pos.pnl >= 0 ? 'positive' : 'negative'} font-mono">
                                    ${pos.pnl >= 0 ? '+' : ''}$${pos.pnl.toFixed(2)} (${(pos.pnl_pct * 100).toFixed(1)}%)
                                </span>
                            </div>
                        </div>
                        <p class="mt-2 text-sm">${pos.question}</p>
                        <div class="mt-2 text-xs text-gray-500">
                            Entry: ${(pos.entry * 100).toFixed(1)}% → Current: ${(pos.current * 100).toFixed(1)}% | Size: $${pos.size.toFixed(2)}
                        </div>
                    </div>
                `).join('');
            }

            // Learning stats
            const learningStats = document.getElementById('learning-stats');
            const catStats = data.category_stats || {};
            const cats = Object.entries(catStats).sort((a, b) => b[1].accuracy - a[1].accuracy);
            
            if (cats.length === 0) {
                learningStats.innerHTML = '<p class="text-gray-500">No learning data yet</p>';
            } else {
                learningStats.innerHTML = cats.slice(0, 6).map(([cat, stats]) => `
                    <div class="flex justify-between items-center py-1">
                        <span class="capitalize">${cat}</span>
                        <span class="font-mono">
                            ${(stats.accuracy * 100).toFixed(0)}% win | 
                            <span class="${stats.total_pnl >= 0 ? 'positive' : 'negative'}">
                                ${stats.total_pnl >= 0 ? '+' : ''}$${stats.total_pnl.toFixed(0)}
                            </span>
                        </span>
                    </div>
                `).join('');
            }

            // Recent trades
            const recentTrades = document.getElementById('recent-trades');
            const trades = data.recent_trades || [];
            
            if (trades.length === 0) {
                recentTrades.innerHTML = '<p class="text-gray-500">No trades yet</p>';
            } else {
                recentTrades.innerHTML = trades.slice(0, 5).map(trade => `
                    <div class="flex justify-between items-center py-1 text-sm">
                        <span>
                            ${trade.is_win ? '✅' : '❌'} ${trade.direction} on ${trade.category}
                        </span>
                        <span class="font-mono ${trade.pnl >= 0 ? 'positive' : 'negative'}">
                            ${trade.pnl >= 0 ? '+' : ''}${trade.pnl.toFixed(1)}%
                        </span>
                    </div>
                `).join('');
            }

            // Update timestamp
            document.getElementById('last-update').textContent = new Date().toLocaleTimeString();
        }

        // Initial fetch and auto-refresh
        fetchData();
        setInterval(fetchData, 30000);
    </script>
</body>
</html>
"""


# === API Endpoints ===

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the dashboard HTML."""
    return DASHBOARD_HTML


@app.get("/api/status")
async def get_status():
    """Get full bot status as JSON."""
    portfolio = position_manager.get_portfolio_state()
    positions = position_manager.get_active_positions()
    
    # Get learning stats
    cat_stats = learning_loop.get_category_stats()
    recent_trades = learning_loop.get_recent_trades(limit=10)
    
    return {
        "mode": "PAPER" if config.paper_trading else "LIVE",
        "portfolio": {
            "total_bankroll": portfolio.total_bankroll,
            "cash_available": portfolio.cash_available,
            "total_exposure": portfolio.total_exposure,
            "exposure_pct": portfolio.exposure_pct,
            "unrealized_pnl": portfolio.unrealized_pnl,
            "realized_pnl": portfolio.realized_pnl,
        },
        "positions": [
            {
                "market_id": p.market_id,
                "question": p.question[:80] + "..." if len(p.question) > 80 else p.question,
                "direction": p.direction.value,
                "size": p.current_size_usd,
                "entry": p.avg_entry_price,
                "current": p.current_price,
                "pnl": p.unrealized_pnl,
                "pnl_pct": p.unrealized_pnl_pct,
                "status": p.status.value,
                "tier": p.tier,
            }
            for p in positions
        ],
        "category_stats": {
            cat: {
                "trades": stats.trades,
                "wins": stats.wins,
                "accuracy": stats.accuracy,
                "total_pnl": stats.total_pnl,
                "weight": stats.weight,
            }
            for cat, stats in cat_stats.items()
        },
        "recent_trades": recent_trades,
    }


@app.get("/api/positions")
async def get_positions():
    """Get active positions."""
    positions = position_manager.get_active_positions()
    return {
        "count": len(positions),
        "positions": [
            {
                "id": p.id,
                "market_id": p.market_id,
                "question": p.question,
                "direction": p.direction.value,
                "tier": p.tier,
                "size_usd": p.current_size_usd,
                "avg_entry": p.avg_entry_price,
                "current_price": p.current_price,
                "unrealized_pnl": p.unrealized_pnl,
                "unrealized_pnl_pct": p.unrealized_pnl_pct,
                "status": p.status.value,
                "created_at": p.created_at.isoformat(),
            }
            for p in positions
        ]
    }


@app.get("/api/portfolio")
async def get_portfolio():
    """Get portfolio state."""
    portfolio = position_manager.get_portfolio_state()
    return {
        "total_bankroll": portfolio.total_bankroll,
        "cash_available": portfolio.cash_available,
        "total_exposure": portfolio.total_exposure,
        "exposure_pct": portfolio.exposure_pct,
        "position_count": portfolio.position_count,
        "unrealized_pnl": portfolio.unrealized_pnl,
        "realized_pnl": portfolio.realized_pnl,
        "largest_position_pct": portfolio.largest_position_pct,
        "avg_position_size": portfolio.avg_position_size,
    }


@app.get("/api/learning")
async def get_learning():
    """Get learning stats."""
    return {
        "category_stats": {
            cat: {
                "trades": stats.trades,
                "wins": stats.wins,
                "accuracy": stats.accuracy,
                "avg_edge": stats.avg_edge,
                "avg_pnl": stats.avg_pnl,
                "total_pnl": stats.total_pnl,
                "weight": stats.weight,
            }
            for cat, stats in learning_loop.get_category_stats().items()
        },
        "edge_buckets": learning_loop.get_edge_bucket_stats(),
        "source_stats": learning_loop.get_source_stats(),
        "trade_count": learning_loop.get_trade_count(),
    }


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# === Run ===

def main():
    """Run the dashboard server."""
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║           🎯 V6 Alpha Hunter Dashboard                       ║
╠══════════════════════════════════════════════════════════════╣
║  URL: http://localhost:{config.dashboard_port}                          ║
║  Mode: {'PAPER' if config.paper_trading else 'LIVE'}                                              ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    uvicorn.run(
        app,
        host=config.dashboard_host,
        port=config.dashboard_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
