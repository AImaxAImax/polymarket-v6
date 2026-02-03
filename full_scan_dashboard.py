#!/usr/bin/env python3
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import sqlite3
import uvicorn

app = FastAPI()
DB = "data/markets.db"

HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>V6 Full Scan Dashboard</title>
    <meta http-equiv="refresh" content="10">
    <style>
        body {{ background: #0d1117; color: #c9d1d9; font-family: system-ui; padding: 20px; max-width: 1400px; margin: 0 auto; }}
        h1 {{ color: #58a6ff; }}
        h2 {{ color: #8b949e; margin-top: 30px; }}
        .stats {{ display: flex; gap: 15px; margin: 20px 0; flex-wrap: wrap; }}
        .stat {{ background: #161b22; padding: 15px 20px; border-radius: 8px; min-width: 100px; }}
        .stat-value {{ font-size: 1.8em; font-weight: bold; color: #58a6ff; }}
        .stat-label {{ color: #8b949e; font-size: 0.9em; }}
        .progress-bar {{ background: #21262d; border-radius: 8px; height: 30px; margin: 20px 0; overflow: hidden; }}
        .progress-fill {{ background: linear-gradient(90deg, #238636, #3fb950); height: 100%; transition: width 0.5s; display: flex; align-items: center; justify-content: center; font-weight: bold; }}
        table {{ width: 100%; border-collapse: collapse; background: #161b22; border-radius: 8px; margin-bottom: 20px; }}
        th {{ background: #21262d; padding: 12px; text-align: left; color: #8b949e; }}
        td {{ padding: 12px; border-top: 1px solid #30363d; }}
        tr:hover {{ background: #1f2428; }}
        .yes {{ color: #3fb950; }} .no {{ color: #f85149; }}
        .edge {{ font-weight: bold; font-size: 1.1em; }}
        .bet {{ background: #238636; color: white; padding: 2px 8px; border-radius: 4px; }}
        .pending {{ background: #6e7681; color: white; padding: 2px 8px; border-radius: 4px; }}
        .skip {{ background: #da3633; color: white; padding: 2px 8px; border-radius: 4px; }}
        .bet-card {{ background: #161b22; border: 2px solid #238636; border-radius: 12px; padding: 20px; margin: 15px 0; }}
        .bet-card h3 {{ color: #3fb950; margin: 0 0 10px 0; }}
        .bet-card .reasoning {{ background: #0d1117; padding: 15px; border-radius: 8px; margin-top: 15px; color: #8b949e; line-height: 1.5; }}
    </style>
</head>
<body>
    <h1>🚀 V6 Full Polymarket Scan</h1>
    
    <div class="progress-bar">
        <div class="progress-fill" style="width: {progress_pct}%">{scanned:,} / {total:,} ({progress_pct:.1f}%)</div>
    </div>
    
    <div class="stats">
        <div class="stat"><div class="stat-value">{scanned:,}</div><div class="stat-label">Scanned</div></div>
        <div class="stat"><div class="stat-value">{remaining:,}</div><div class="stat-label">Remaining</div></div>
        <div class="stat"><div class="stat-value">{alpha_count}</div><div class="stat-label">Alpha Found</div></div>
        <div class="stat"><div class="stat-value">{hit_rate:.1f}%</div><div class="stat-label">Hit Rate</div></div>
        <div class="stat"><div class="stat-value">{validated_count}</div><div class="stat-label">Validated</div></div>
        <div class="stat"><div class="stat-value">{bet_count}</div><div class="stat-label">✅ BET Recs</div></div>
    </div>
    
    {bet_cards}
    
    <h2>All Alpha Opportunities ({alpha_count} found)</h2>
    <table>
        <tr><th>#</th><th>Question</th><th>Dir</th><th>Edge</th><th>Price</th><th>Conf</th><th>Status</th></tr>
        {rows}
    </table>
    <p style="color:#6e7681;margin-top:20px">Auto-refreshes every 10s | Scanner: 20 parallel requests</p>
</body>
</html>
'''

@app.get("/", response_class=HTMLResponse)
async def home():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    
    total = c.execute("SELECT COUNT(*) FROM markets WHERE liquidity >= 500 AND end_date IS NOT NULL AND end_date >= datetime('now', '+7 days')").fetchone()[0]
    
    # Get scanned count from progress table
    try:
        scanned = c.execute("SELECT COUNT(*) FROM full_scan_progress").fetchone()[0]
    except:
        scanned = 0
    
    # Get alpha count
    try:
        alpha = c.execute("SELECT COUNT(*) FROM full_scan_alpha").fetchone()[0]
    except:
        alpha = 0
    
    # If no progress table yet, estimate from alpha
    if scanned == 0 and alpha > 0:
        scanned = int(alpha / 0.028)
    
    remaining = max(0, total - scanned)
    progress_pct = min(100, (scanned / total * 100)) if total > 0 else 0
    hit_rate = (alpha / scanned * 100) if scanned > 0 else 0
    
    try:
        validated = c.execute("SELECT COUNT(*) FROM full_scan_validated").fetchone()[0]
        bets = c.execute("SELECT COUNT(*) FROM full_scan_validated WHERE recommendation='BET'").fetchone()[0]
    except:
        validated, bets = 0, 0
    
    # BET cards with reasoning
    bet_cards = ""
    try:
        bet_data = c.execute('''
            SELECT v.question, v.direction, v.edge, v.market_price, v.reasoning
            FROM full_scan_validated v
            WHERE v.recommendation = 'BET'
            ORDER BY v.edge DESC
        ''').fetchall()
        
        if bet_data:
            bet_cards = "<h2>✅ Validated BET Recommendations</h2>"
            for q, d, e, p, reasoning in bet_data:
                bet_cards += f'''
                <div class="bet-card">
                    <h3>{q}</h3>
                    <div style="display:flex;gap:20px;margin:10px 0;">
                        <span>Direction: <strong class="{d.lower()}">{d}</strong></span>
                        <span>Edge: <strong style="color:#3fb950;font-size:1.3em;">{e*100:.0f}%</strong></span>
                        <span>Market: {p*100:.0f}%</span>
                    </div>
                    <div class="reasoning">
                        <strong>🧠 Why we like this bet:</strong><br>
                        {reasoning if reasoning else "Pending validation..."}
                    </div>
                </div>
                '''
    except:
        pass
    
    # Table rows
    rows = ""
    try:
        data = c.execute('''
            SELECT a.question, a.direction, a.edge, a.market_price, a.confidence,
                   COALESCE(v.recommendation, 'PENDING') as status
            FROM full_scan_alpha a
            LEFT JOIN full_scan_validated v ON a.market_id = v.market_id
            ORDER BY a.edge DESC LIMIT 50
        ''').fetchall()
        for i, (q, d, e, p, conf, status) in enumerate(data, 1):
            status_class = 'bet' if status == 'BET' else 'skip' if status == 'SKIP' else 'pending'
            rows += f'''<tr>
                <td>{i}</td>
                <td>{q[:60]}{'...' if len(q)>60 else ''}</td>
                <td class="{d.lower()}">{d}</td>
                <td class="edge">{e*100:.0f}%</td>
                <td>{p*100:.0f}%</td>
                <td>{conf}</td>
                <td><span class="{status_class}">{status}</span></td>
            </tr>'''
    except Exception as e:
        rows = f"<tr><td colspan='7'>Loading...</td></tr>"
    
    conn.close()
    return HTML.format(
        total=total, scanned=scanned, remaining=remaining, 
        progress_pct=progress_pct, alpha_count=alpha, hit_rate=hit_rate,
        validated_count=validated, bet_count=bets, bet_cards=bet_cards, rows=rows
    )

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8900)
