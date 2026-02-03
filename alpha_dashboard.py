#!/usr/bin/env python3
"""Alpha Leaderboard Dashboard - Shows best opportunities as they're found"""
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import sqlite3
import uvicorn

app = FastAPI(title="V6 Alpha Leaderboard")
DB_PATH = "data/markets.db"

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>V6 Alpha Leaderboard</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body {{ background: #0d1117; color: #c9d1d9; font-family: -apple-system, BlinkMacSystemFont, sans-serif; padding: 20px; }}
        h1 {{ color: #58a6ff; }}
        .stats {{ display: flex; gap: 20px; margin-bottom: 20px; }}
        .stat {{ background: #161b22; padding: 15px 25px; border-radius: 8px; }}
        .stat-value {{ font-size: 2em; font-weight: bold; color: #58a6ff; }}
        .stat-label {{ color: #8b949e; font-size: 0.9em; }}
        table {{ width: 100%; border-collapse: collapse; background: #161b22; border-radius: 8px; overflow: hidden; }}
        th {{ background: #21262d; padding: 12px; text-align: left; color: #8b949e; }}
        td {{ padding: 12px; border-top: 1px solid #30363d; }}
        tr:hover {{ background: #1f2428; }}
        .edge {{ color: #3fb950; font-weight: bold; font-size: 1.1em; }}
        .direction-YES {{ color: #3fb950; }}
        .direction-NO {{ color: #f85149; }}
        .confidence-HIGH {{ color: #3fb950; }}
        .confidence-MEDIUM {{ color: #d29922; }}
        .confidence-LOW {{ color: #8b949e; }}
        .question {{ max-width: 400px; }}
        .refresh {{ color: #8b949e; font-size: 0.8em; margin-top: 10px; }}
    </style>
</head>
<body>
    <h1>🎯 V6 Alpha Leaderboard</h1>
    <div class="stats">
        <div class="stat"><div class="stat-value">{total_scans}</div><div class="stat-label">Markets Scanned</div></div>
        <div class="stat"><div class="stat-value">{alpha_count}</div><div class="stat-label">Alpha Found (15%+)</div></div>
        <div class="stat"><div class="stat-value">{total_markets}</div><div class="stat-label">Total Markets</div></div>
        <div class="stat"><div class="stat-value">{progress:.1f}%</div><div class="stat-label">Progress</div></div>
    </div>
    <table>
        <tr><th>#</th><th>Question</th><th>Direction</th><th>Edge</th><th>Market Price</th><th>Our Estimate</th><th>Confidence</th></tr>
        {rows}
    </table>
    <p class="refresh">Auto-refreshes every 30 seconds</p>
</body>
</html>
'''

@app.get("/", response_class=HTMLResponse)
async def home():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    total_scans = c.execute("SELECT COUNT(*) FROM alpha_scans_v3").fetchone()[0]
    alpha_count = c.execute("SELECT COUNT(*) FROM alpha_scans_v3 WHERE edge >= 0.15").fetchone()[0]
    total_markets = c.execute("SELECT COUNT(*) FROM markets WHERE liquidity >= 100").fetchone()[0]
    progress = (total_scans / total_markets * 100) if total_markets > 0 else 0
    
    rows_data = c.execute('''
        SELECT question, direction, edge, market_price, estimated_prob, confidence 
        FROM alpha_scans_v3 WHERE edge >= 0.10 ORDER BY edge DESC LIMIT 50
    ''').fetchall()
    conn.close()
    
    rows = ""
    for i, (q, d, e, mp, ep, conf) in enumerate(rows_data, 1):
        rows += f'''<tr>
            <td>{i}</td>
            <td class="question">{q[:80]}{'...' if len(q) > 80 else ''}</td>
            <td class="direction-{d}">{d}</td>
            <td class="edge">{e*100:.1f}%</td>
            <td>{mp*100:.1f}%</td>
            <td>{ep*100:.1f}%</td>
            <td class="confidence-{conf}">{conf}</td>
        </tr>'''
    
    return HTML_TEMPLATE.format(
        total_scans=total_scans,
        alpha_count=alpha_count,
        total_markets=total_markets,
        progress=progress,
        rows=rows
    )

@app.get("/api/alpha")
async def api_alpha():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    data = c.execute('''
        SELECT market_id, question, direction, edge, market_price, estimated_prob, confidence, reasoning
        FROM alpha_scans_v3 WHERE edge >= 0.10 ORDER BY edge DESC LIMIT 50
    ''').fetchall()
    conn.close()
    return [{"id": r[0], "question": r[1], "direction": r[2], "edge": r[3], "price": r[4], "estimate": r[5], "confidence": r[6], "reasoning": r[7]} for r in data]

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8899)
