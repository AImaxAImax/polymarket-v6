# Learning Report: 2026-01-04 to 2026-02-03

## Summary
- **Total Trades:** 9
- **Wins:** 5 (55.6%)
- **Total P&L:** -146.0%

## Category Performance

| Category | Trades | Wins | Accuracy | Avg P&L | Weight |
|----------|--------|------|----------|---------|--------|
| entertainment | 2 | 2 | 100.0% | +100.0% | 1.0 |
| tech | 3 | 2 | 66.7% | -30.8% | 1.0 |
| crypto | 2 | 1 | 50.0% | -26.7% | 1.0 |
| politics | 1 | 0 | 0.0% | -100.0% | 1.0 |
| sports | 1 | 0 | 0.0% | -100.0% | 1.0 |

## Winning Patterns

### Sweet Spot Edge: 10-20%
- **Description:** Trades with 10-20% edge have the highest win rate
- **Win Rate:** 66.7% (n=3)
- **Confidence:** low
- **Action:** Prioritize opportunities in the 10-20% edge range

### Reliable Source: official_source
- **Description:** Trades using official_source have high win rate
- **Win Rate:** 83.3% (n=6)
- **Confidence:** medium
- **Action:** Weight official_source signals higher in conviction

### Unreliable Source: news_api
- **Description:** Trades relying on news_api underperform
- **Win Rate:** 33.3% (n=6)
- **Confidence:** low
- **Action:** Reduce weight of news_api in conviction scoring

### Optimal Resolution Time: 30-90days
- **Description:** Trades resolving in 30-90days have highest accuracy
- **Win Rate:** 100.0% (n=3)
- **Confidence:** low
- **Action:** Prefer markets with ~30-90days resolution time

## Edge Analysis

- **Best Edge Bucket:** 10-20
- **Worst Edge Bucket:** 0-10

## Source Reliability

### Most Reliable
- official_source: 83.3%
- twitter: 66.7%
- reddit: 60.0%
- ai_analysis: 55.6%
- news_api: 33.3%

### Least Reliable
- news_api: 33.3%
- ai_analysis: 55.6%
- reddit: 60.0%

## Recommendations

1. Weight official_source signals higher in conviction