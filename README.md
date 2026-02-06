# V6 Alpha Hunter — Polymarket Trading Bot

AI-powered prediction market scanner and trading system for [Polymarket](https://polymarket.com).

## Architecture

**3-stage pipeline:**

1. **Alpha Scanner** (`alpha_scanner.py`) — Scans all active Polymarket markets, gets AI probability estimates via Ollama, flags opportunities with 20%+ edge. Uses Bayesian anchoring to prevent LLM hallucination (tells the model the market price, requires reasoning for large disagreements, caps max edge at 50%).

2. **Deep Research** (`deep_research.py`) — Validates top 50 alpha opportunities with multi-source web research via SearXNG. Generates 5-10 queries per market, extracts key facts, uses AI to synthesize and update probability estimates.

3. **Conviction Engine** (`conviction_engine.py`) — Scores opportunities 0-10 on six weighted factors: edge size (25%), source quality (20%), source agreement (20%), recency (15%), AI confidence delta (10%), category track record (10%). Approves trades at 8+ conviction.

**Position management:**

- `position_manager.py` — 3-tier scale-in (33%/33%/34%), 4-level take profit, hard stop loss (-20%), trailing stop (-10% from peak after +10% gain). SQLite persistence with full audit trail.
- `risk_manager.py` — Fractional Kelly sizing, max 10% single position, 50% total exposure, 10 concurrent positions.
- `learning_loop.py` — Tracks outcomes by category, edge bucket, source type. Updates conviction weights via EMA.

## Quick Start

```bash
# 1. Clone and install
git clone <repo> && cd polybot-v6
pip install -r requirements.txt

# 2. Configure endpoints
cp .env.example .env
# Edit .env with your Ollama and SearXNG URLs

# 3. Scan for opportunities
python -m src.bot scan

# 4. Paper trading
python -m src.bot run --paper

# 5. Live trading (requires explicit confirmation)
python -m src.bot run --live --confirm
```

## Configuration

All network endpoints are configurable via `.env`:

```env
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:32b
SEARXNG_URL=http://localhost:8888
```

See `.env.example` for all options.

## Commands

| Command | Description |
|---------|-------------|
| `python -m src.bot scan` | Scan markets and show approved opportunities |
| `python -m src.bot run --paper` | Start paper trading loop |
| `python -m src.bot run --live --confirm` | Start live trading (real money) |
| `python -m src.bot status` | Show positions and portfolio state |
| `python -m src.bot report` | Show learning/performance report |
| `python -m src.dashboard` | Start web dashboard on port 8898 |

## Project Structure

```
src/
├── bot.py                 # Main orchestrator & CLI
├── bot_config.py          # Bot-level configuration
├── config.py              # V6 config with .env support
├── models.py              # Data models (Market, Position, etc.)
├── alpha_scanner.py       # Stage 1: Market scanning + AI estimates
├── deep_research.py       # Stage 2: Web research validation
├── conviction_engine.py   # Stage 3: Scoring & trade approval
├── position_manager.py    # Position lifecycle (scale-in/out, TP/SL)
├── risk_manager.py        # Risk limits & Kelly sizing
├── learning_loop.py       # Outcome tracking & weight updates
├── pattern_analyzer.py    # Winning pattern identification
└── dashboard.py           # FastAPI web dashboard
```

## Requirements

- Python 3.11+
- [Ollama](https://ollama.com) running locally (or remote via Tailscale)
- [SearXNG](https://docs.searxng.org) instance for web research
- SQLite (included with Python)

## Safety

- **Paper trading is the default.** Live trading requires `--live --confirm`.
- Hard stop loss at -20%, trailing stop at -10% from peak.
- Max 50% portfolio exposure, max 10% single position.
- All trades logged with full audit trail in SQLite.
