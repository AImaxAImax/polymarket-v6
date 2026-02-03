import asyncio
import aiohttp
import sqlite3
from datetime import datetime

POLYMARKET_API = "https://gamma-api.polymarket.com"

async def bulk_import():
    conn = sqlite3.connect('data/markets.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS markets (
        id TEXT PRIMARY KEY, question TEXT, outcome_prices TEXT,
        volume REAL, liquidity REAL, end_date TEXT,
        created_at TEXT, updated_at TEXT, imported_at TEXT
    )''')
    conn.commit()
    
    async with aiohttp.ClientSession() as session:
        markets = []
        offset = 0
        print("Fetching ALL markets from Polymarket...")
        
        while True:
            params = {"limit": 100, "offset": offset, "active": "true", "closed": "false"}
            try:
                async with session.get(f"{POLYMARKET_API}/markets", params=params, timeout=30) as resp:
                    if resp.status != 200:
                        offset += 100
                        continue
                    data = await resp.json()
                    if not data:
                        break
                    markets.extend(data)
                    offset += 100
                    if offset % 1000 == 0:
                        print(f"  {len(markets)} markets...")
            except Exception as e:
                print(f"Error: {e}")
                offset += 100
                continue
        
        print(f"Total: {len(markets)} markets")
        print("Saving to database...")
        
        now = datetime.utcnow().isoformat()
        for m in markets:
            try:
                c.execute('''INSERT OR REPLACE INTO markets VALUES (?,?,?,?,?,?,?,?,?)''',
                    (m.get('id'), m.get('question'), m.get('outcomePrices'),
                     float(m.get('volume',0) or 0), float(m.get('liquidity',0) or 0),
                     m.get('endDate'), m.get('createdAt'), m.get('updatedAt'), now))
            except: pass
        
        conn.commit()
        count = c.execute('SELECT COUNT(*) FROM markets').fetchone()[0]
        print(f"Done! {count} markets in database")
        conn.close()

asyncio.run(bulk_import())
