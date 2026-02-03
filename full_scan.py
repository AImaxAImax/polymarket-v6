#!/usr/bin/env python3
"""Full-scale parallel scanner with checkpointing

Features:
- Resumes from where it left off (doesn't drop tables)
- Skips already-scanned markets
- Git checkpoint every 100 alpha finds
- Higher concurrency
- Filters out markets expiring in <7 days (quick win)
"""
import asyncio
import aiohttp
import sqlite3
import json
import re
import os
import subprocess
from datetime import datetime, timezone, timedelta

SEARXNG_URL = "http://100.112.76.34:8888/search"
OLLAMA_URL = "http://100.112.76.34:11434/api/generate"
SCANNER_MODEL = "qwen2.5:32b"
DB_PATH = "data/markets.db"

EDGE_CAPS = {"LOW": 0.15, "MEDIUM": 0.30, "HIGH": 0.50}
MIN_EDGE = 0.08
CHECKPOINT_INTERVAL = 25  # Git commit every N alpha finds
MIN_DAYS_TO_EXPIRY = 7  # Skip markets expiring in <7 days

class FullScanner:
    def __init__(self, max_concurrent: int = 40):
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.stats = {"scanned": 0, "alpha": 0, "no_edge": 0, "errors": 0, "skipped": 0, "short_term": 0}
        self.last_checkpoint = 0
        self.setup_db()
    
    def setup_db(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # CREATE IF NOT EXISTS - preserves existing data!
        c.execute('''CREATE TABLE IF NOT EXISTS full_scan_alpha (
            market_id TEXT PRIMARY KEY,
            question TEXT,
            market_price REAL,
            estimated_prob REAL,
            edge REAL,
            direction TEXT,
            confidence TEXT,
            reasoning TEXT,
            scanned_at TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS full_scan_validated (
            market_id TEXT PRIMARY KEY,
            question TEXT,
            direction TEXT,
            edge REAL,
            market_price REAL,
            validation_status TEXT,
            recommendation TEXT,
            reasoning TEXT,
            validated_at TEXT
        )''')
        # Track scanned markets (even if no alpha)
        c.execute('''CREATE TABLE IF NOT EXISTS full_scan_progress (
            market_id TEXT PRIMARY KEY,
            scanned_at TEXT
        )''')
        conn.commit()
        conn.close()
    
    def git_checkpoint(self, msg):
        """Save progress to git."""
        try:
            subprocess.run(['git', 'add', '-f', 'data/markets.db'], cwd='/home/max/projects/polymarket-v6', capture_output=True)
            subprocess.run(['git', 'commit', '-m', msg], cwd='/home/max/projects/polymarket-v6', capture_output=True)
            subprocess.run(['git', 'push'], cwd='/home/max/projects/polymarket-v6', capture_output=True)
            print(f"  💾 Git checkpoint: {msg}")
        except:
            pass
    
    async def search(self, session, query):
        try:
            async with session.get(SEARXNG_URL, params={"q": query, "format": "json"}, timeout=10) as r:
                if r.status == 200:
                    data = await r.json()
                    return "\n".join([f"- {x.get('title')}: {x.get('content','')[:150]}" for x in data.get("results",[])[:4]])
        except:
            pass
        return ""
    
    async def scan_market(self, session, market):
        async with self.semaphore:
            self.stats["scanned"] += 1
            
            try:
                prices = json.loads(market["outcome_prices"])
                price = float(prices[0])
            except:
                return None
            
            if price < 0.02 or price > 0.98:
                return None
            
            q = market["question"]
            research = await self.search(session, f"{q} news prediction 2026")
            
            prompt = f"""Prediction market analyst. Find mispriced markets.

Q: {q}
Market YES: {price:.1%}

Research:
{research}

Does research suggest market is WRONG? If yes, explain why.
If no edge, say "NO EDGE".

ANALYSIS: [reasoning]
EDGE_FOUND: [YES/NO]
PROBABILITY: [num]%
CONFIDENCE: [LOW/MEDIUM/HIGH]"""
            
            try:
                async with session.post(OLLAMA_URL, json={"model": SCANNER_MODEL, "prompt": prompt, "stream": False}, timeout=60) as r:
                    if r.status != 200:
                        self.stats["errors"] += 1
                        return None
                    data = await r.json()
                    resp = data.get("response", "")
            except Exception as e:
                self.stats["errors"] += 1
                return None
            
            # Mark as scanned
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('INSERT OR IGNORE INTO full_scan_progress VALUES (?, ?)', 
                      (market["id"], datetime.now(timezone.utc).isoformat()))
            conn.commit()
            conn.close()
            
            if "NO EDGE" in resp.upper() or "EDGE_FOUND: NO" in resp.upper():
                self.stats["no_edge"] += 1
                return None
            
            prob_m = re.search(r'PROBABILITY:\s*(\d+)%', resp)
            conf_m = re.search(r'CONFIDENCE:\s*(LOW|MEDIUM|HIGH)', resp, re.I)
            
            if not prob_m:
                return None
            
            prob = int(prob_m.group(1)) / 100
            conf = conf_m.group(1).upper() if conf_m else "LOW"
            
            # Edge cap
            max_edge = EDGE_CAPS.get(conf, 0.15)
            if abs(prob - price) > max_edge:
                prob = price + max_edge if prob > price else price - max_edge
            
            if prob > price:
                direction, edge = "YES", prob - price
            else:
                direction, edge = "NO", price - prob
            
            if edge < MIN_EDGE:
                return None
            
            self.stats["alpha"] += 1
            
            # Save alpha
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('INSERT OR REPLACE INTO full_scan_alpha VALUES (?,?,?,?,?,?,?,?,?)',
                (market["id"], q, price, prob, edge, direction, conf, resp[:500], datetime.now(timezone.utc).isoformat()))
            conn.commit()
            conn.close()
            
            # Git checkpoint every N alpha
            if self.stats["alpha"] - self.last_checkpoint >= CHECKPOINT_INTERVAL:
                self.git_checkpoint(f"checkpoint: {self.stats['alpha']} alpha found")
                self.last_checkpoint = self.stats["alpha"]
            
            return {"id": market["id"], "question": q, "direction": direction, "edge": edge, "price": price, "confidence": conf}
    
    async def run_scanner(self, min_liquidity=500):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Get already scanned market IDs
        scanned_ids = set(r[0] for r in c.execute('SELECT market_id FROM full_scan_progress').fetchall())
        alpha_ids = set(r[0] for r in c.execute('SELECT market_id FROM full_scan_alpha').fetchall())
        already_done = scanned_ids | alpha_ids
        
        # Calculate min end_date (7 days from now)
        min_end_date = (datetime.now(timezone.utc) + timedelta(days=MIN_DAYS_TO_EXPIRY)).isoformat()
        
        # Get markets to scan (excluding already done + short-term)
        query = f'''SELECT id, question, outcome_prices, end_date FROM markets 
                    WHERE liquidity >= {min_liquidity} 
                    AND end_date IS NOT NULL 
                    AND end_date >= ? 
                    ORDER BY liquidity DESC'''
        all_markets = [{'id': r[0], 'question': r[1], 'outcome_prices': r[2], 'end_date': r[3]} 
                       for r in c.execute(query, (min_end_date,)).fetchall()]
        
        markets = [m for m in all_markets if m['id'] not in already_done]
        
        existing_alpha = c.execute('SELECT COUNT(*) FROM full_scan_alpha').fetchone()[0]
        conn.close()
        
        print(f"🚀 FULL SCAN: {len(all_markets):,} markets (${min_liquidity}+ liquidity, >{MIN_DAYS_TO_EXPIRY}d to expiry)")
        print(f"   Already scanned: {len(already_done):,}")
        print(f"   Remaining: {len(markets):,}")
        print(f"   Existing alpha: {existing_alpha}")
        print(f"   Concurrency: {self.max_concurrent} parallel")
        print(f"   Model: {SCANNER_MODEL}")
        print(f"   Checkpoint: every {CHECKPOINT_INTERVAL} alpha")
        print()
        
        if not markets:
            print("✅ All markets already scanned!")
            return
        
        self.stats["alpha"] = existing_alpha
        self.last_checkpoint = existing_alpha
        
        async with aiohttp.ClientSession() as session:
            tasks = [self.scan_market(session, m) for m in markets]
            for i, coro in enumerate(asyncio.as_completed(tasks)):
                result = await coro
                if result:
                    print(f"[{i+1:,}/{len(markets):,}] 🎯 {result['direction']} {result['edge']*100:.0f}%: {result['question'][:50]}")
                elif (i+1) % 500 == 0:
                    print(f"[{i+1:,}/{len(markets):,}] Progress... α:{self.stats['alpha']} no_edge:{self.stats['no_edge']} err:{self.stats['errors']}")
        
        # Final checkpoint
        self.git_checkpoint(f"scan complete: {self.stats['alpha']} alpha found")
        
        print(f"\n{'='*60}")
        print(f"SCAN COMPLETE")
        print(f"Scanned: {self.stats['scanned']:,}")
        print(f"Alpha found: {self.stats['alpha']} ({self.stats['alpha']/max(1,self.stats['scanned']+len(already_done))*100:.1f}%)")
        print(f"No edge: {self.stats['no_edge']:,}")
        print(f"Errors: {self.stats['errors']}")
        print(f"{'='*60}")

async def main():
    scanner = FullScanner(max_concurrent=40)  # Increased from 12 to 20
    await scanner.run_scanner(min_liquidity=500)

if __name__ == "__main__":
    asyncio.run(main())
