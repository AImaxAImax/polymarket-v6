# Polymarket V6 - Research-First Architecture

A prediction market scanner with research-first architecture. Fetches markets from Polymarket, researches them via SearXNG, and analyzes with LLM to find trading opportunities.

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────┐
│ Market Fetcher  │────▶│ Research Engine  │────▶│  Analyzer   │
│ (Polymarket)    │     │ (SearXNG)        │     │ (Ollama)    │
└─────────────────┘     └──────────────────┘     └─────────────┘
        │                        │                      │
        └────────────────────────┴──────────────────────┘
                                 │
                        ┌────────▼────────┐
                        │    SQLite DB    │
                        │  (markets.db)   │
                        └─────────────────┘
```

## Installation

```bash
cd /home/max/projects/polymarket-v6
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Usage

### Full Scan
Fetch all markets, research new/stale ones, analyze with LLM:
```bash
python -m src.scanner --full
python -m src.scanner --full --limit 100  # Test with 100 markets
```

### Incremental Scan
Only process truly NEW markets discovered since last run:
```bash
python -m src.scanner --incremental
```

### Maintenance
Update prices, clean resolved markets:
```bash
python -m src.scanner --maintenance
```

### View Opportunities
```bash
python -m src.scanner --opportunities
python -m src.scanner --opportunities --min-edge 0.10  # Higher edge threshold
```

### Statistics
```bash
python -m src.scanner --stats
```

## Configuration

| Flag | Default | Description |
|------|---------|-------------|
| `--db` | `data/markets.db` | SQLite database path |
| `--searxng` | `http://100.112.76.34:8888` | SearXNG URL |
| `--ollama` | `http://100.112.76.34:11434` | Ollama URL |
| `--model` | `qwen2.5:32b` | Ollama model |
| `--limit` | None | Limit markets to process |
| `--min-edge` | 0.05 | Minimum edge for BUY signal |
| `--min-confidence` | 0.6 | Minimum confidence |

## Database Schema

- `markets` table stores all market data
- Tracks `first_seen_at` to identify new markets
- Preserves research and analysis on upsert
- Indexes on status, edge, and first_seen

## Signal Logic

- **BUY**: Edge > 5% AND Confidence > 60%
- **AVOID**: Edge < -10% AND Confidence > 70%
- **SKIP**: Everything else

## Bet Sizing

Conservative sizing based on liquidity:
- Liquidity < $500: max $10
- Liquidity $500-2000: max $25
- Liquidity $2000-10000: max $50
- Liquidity > $10000: max $100

Actual size scaled by edge × confidence.

## Key Features

1. **Research-First**: Web research happens BEFORE LLM analysis
2. **No Liquidity Filter**: Catches small market opportunities
3. **Parallel Research**: 200 concurrent SearXNG searches
4. **Incremental Mode**: Only processes truly new markets
5. **Proper Maintenance**: Cleans resolved markets, updates prices
