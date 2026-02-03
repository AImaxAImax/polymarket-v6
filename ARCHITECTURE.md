# Polymarket V6: Alpha Hunter

**Philosophy:** Quality over quantity. Find 20%+ edge, confirm it's real, bet big, manage risk.

## 🚀 Status: COMPLETE

All components built and integrated!

## CRITICAL: Full Scan Before Any Trade

Before deploying ANY capital, the bot MUST:
1. Scan **ALL ~25,000 markets** (not just a sample)
2. Rank by edge size (highest first)
3. Deep research top 50+ opportunities
4. Score conviction on all researched
5. ONLY THEN deploy capital on 8+ conviction trades

This ensures we find the BEST alpha across the entire market, not just early discoveries.

## Architecture

### Components (6 modules)

| Step | Component | File | Purpose | Status |
|------|-----------|------|---------|--------|
| 1 | **Alpha Scanner** | `alpha_scanner.py` | Scan all markets, flag 20%+ AI vs market discrepancy | ✅ |
| 2 | **Deep Research** | `deep_research.py` | 5-10 web queries per flagged market | ✅ |
| 3 | **Conviction Engine** | `conviction_engine.py` | Score 1-10, require 8+ to trade | ✅ |
| 4 | **Position Manager** | `position_manager.py` | Scale in/out, trailing SL, TP levels | ✅ |
| 5 | **Learning Loop** | `learning_loop.py` | Track outcomes, weight future signals | ✅ |
| 6 | **Main Bot** | `bot.py` | Orchestrator tying all components | ✅ |
| 7 | **Dashboard** | `dashboard.py` | Web UI for monitoring | ✅ |

## Quick Start

```bash
# Scan for opportunities (no trading)
./run.sh scan

# Paper trading (simulated)
./run.sh paper

# Live trading (real money - BE CAREFUL!)
./run.sh live --confirm

# View status
./run.sh status

# Learning report
./run.sh report

# Web dashboard
./run.sh dashboard
```

## Full Scan Flow

```
1. Scan ALL markets (~25k)
   ↓
2. Filter to 20%+ edge
   ↓
3. Sort by edge descending
   ↓
4. Deep research top 50
   ↓
5. Score conviction (0-10)
   ↓
6. Filter to 8+ conviction
   ↓
7. Execute trades (max 3 per cycle)
   ↓
8. Manage positions (TP/SL)
   ↓
9. Learn from outcomes
   ↓
10. Repeat every hour
```

## Key Parameters

- **Alpha threshold:** 20% (AI estimate vs market price)
- **Min conviction:** 8/10 to trade
- **Position sizing:** 3-7% on high conviction (Kelly-scaled)
- **Kelly fraction:** 0.5 (half Kelly)
- **Scale-in tiers:** 3 (33% → 33% → 34%)
- **Take profit:** 25% at TP1 (+15%), TP2 (+25%), TP3 (+40%)
- **Stop loss:** -20% hard stop, -10% trailing after +10% gain
- **Max exposure:** 50% of portfolio
- **Max positions:** 10 concurrent

## Conviction Score Breakdown

| Factor | Weight | Description |
|--------|--------|-------------|
| Edge Size | 25% | How big is the mispricing? |
| Source Quality | 20% | Reuters/AP (10) vs blogs (5) |
| Source Agreement | 20% | Do sources agree or conflict? |
| Recency | 15% | How fresh is the information? |
| AI Confidence Delta | 10% | Did research strengthen conviction? |
| Category Track Record | 10% | Historical win rate in this category |

**Score ≥ 8.0 = Trade approved**

## Position Sizing by Conviction

| Score | Position Size | Tier |
|-------|---------------|------|
| 8.0-8.9 | 3% | Standard |
| 9.0-9.4 | 5% | Large |
| 9.5-10 | 7% | Max |

## Data Sources

- **Polymarket API:** gamma-api.polymarket.com
- **SearXNG:** http://100.112.76.34:8888 (web search)
- **Ollama LLMs:** http://100.112.76.34:11434
  - qwen2.5:32b (primary)
  - deepseek-r1:32b (secondary)

## Learning System

Tracks per-category performance:
- Politics
- Crypto
- Sports/Esports
- Entertainment
- Science/Tech
- Business
- Uncategorized

Categories with >50% win rate get weight boost (1.2x).
Categories with <50% get weight penalty (0.7x).

Also tracks:
- Edge bucket performance (20-30%, 30-40%, etc.)
- Source type reliability
- Time-to-resolution correlations

## File Structure

```
polymarket-v6/
├── src/
│   ├── __init__.py
│   ├── models.py           # Pydantic models
│   ├── config.py           # V6 config (API URLs, thresholds)
│   ├── bot_config.py       # Bot orchestrator config
│   ├── alpha_scanner.py    # Market scanner
│   ├── deep_research.py    # Web research engine
│   ├── conviction_engine.py # Trade scoring
│   ├── risk_manager.py     # Risk calculations
│   ├── position_manager.py # Position tracking & SQLite
│   ├── learning_loop.py    # Outcome tracking
│   ├── pattern_analyzer.py # Pattern discovery
│   ├── bot.py              # Main orchestrator
│   └── dashboard.py        # FastAPI dashboard
├── data/
│   ├── positions.db        # Position history
│   └── learning.db         # Learning data
├── tests/
│   └── ...
├── requirements.txt
├── run.sh
└── ARCHITECTURE.md
```

## Safety Features

1. **Default PAPER mode** - Must explicitly enable live trading
2. **--confirm required** for live trading
3. **Max exposure limit** (50%)
4. **Position size limits** (max 10% per position)
5. **Hard stop loss** (-20%)
6. **Graceful shutdown** on SIGTERM
7. **Full audit logging**
