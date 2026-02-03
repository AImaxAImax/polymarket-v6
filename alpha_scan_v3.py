#!/usr/bin/env python3
"""Alpha Scanner V3: Balanced approach - conservative but not paralyzed

Key principles:
- Research can INFORM judgment, not just provide smoking gun evidence
- BUT must explain HOW research changes your view vs market
- Edge caps still apply based on confidence
- Skip markets where LLM just says "market is probably right"
"""
import asyncio
import aiohttp
import sqlite3
import json
import re
from datetime import datetime, timezone
from typing import Optional
import argparse

SEARXNG_URL = "http://100.112.76.34:8888/search"
OLLAMA_URL = "http://100.112.76.34:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:32b"
DB_PATH = "data/markets.db"

# Max edge allowed per confidence level
EDGE_CAPS = {"LOW": 0.15, "MEDIUM": 0.30, "HIGH": 0.50}
MIN_EDGE = 0.08  # 8% minimum to be considered alpha

class AlphaScanner:
    def __init__(self, max_concurrent: int = 4):
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.setup_db()
        self.stats = {"scanned": 0, "alpha": 0, "no_edge": 0, "capped": 0}
    
    def setup_db(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('DROP TABLE IF EXISTS alpha_scans_v3')
        c.execute('''CREATE TABLE IF NOT EXISTS alpha_scans_v3 (
            market_id TEXT PRIMARY KEY,
            question TEXT,
            market_price REAL,
            estimated_prob REAL,
            raw_estimate REAL,
            edge REAL,
            direction TEXT,
            confidence TEXT,
            reasoning TEXT,
            research_summary TEXT,
            scanned_at TEXT
        )''')
        conn.commit()
        conn.close()
    
    async def search(self, session: aiohttp.ClientSession, query: str) -> str:
        try:
            params = {"q": query, "format": "json", "engines": "google,bing,duckduckgo"}
            async with session.get(SEARXNG_URL, params=params, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("results", [])[:5]
                    return "\n".join([f"- {r.get('title')}: {r.get('content', '')[:200]}" for r in results])
        except:
            pass
        return "No results"
    
    async def analyze(self, session: aiohttp.ClientSession, question: str, research: str, market_price: float) -> dict:
        prompt = f"""You are a prediction market analyst looking for mispriced markets.

QUESTION: {question}
CURRENT MARKET PRICE (YES): {market_price:.1%}

RESEARCH:
{research}

== YOUR TASK ==
Does the research suggest the market is WRONG? If yes, explain specifically why and estimate the true probability.

If the research doesn't help you disagree with the market, say "NO EDGE" and match the market price.

== RESPONSE FORMAT ==
ANALYSIS: [Your specific reasoning - what does the research tell you that the market might be missing?]
EDGE_FOUND: [YES or NO]
PROBABILITY: [number]% (your estimate of TRUE probability)
CONFIDENCE: [LOW/MEDIUM/HIGH based on how strong your evidence is]
"""
        try:
            payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}
            async with session.post(OLLAMA_URL, json=payload, timeout=60) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    response = data.get("response", "")
                    
                    # Parse
                    edge_found = "YES" in response.upper().split("EDGE_FOUND")[1][:20] if "EDGE_FOUND" in response.upper() else False
                    prob_match = re.search(r'PROBABILITY:\s*(\d+)%', response)
                    conf_match = re.search(r'CONFIDENCE:\s*(LOW|MEDIUM|HIGH)', response, re.I)
                    analysis_match = re.search(r'ANALYSIS:\s*(.+?)(?=EDGE_FOUND|$)', response, re.S)
                    
                    prob = int(prob_match.group(1)) / 100 if prob_match else None
                    confidence = conf_match.group(1).upper() if conf_match else "LOW"
                    reasoning = analysis_match.group(1).strip()[:500] if analysis_match else response[:500]
                    
                    # If LLM says no edge, trust it
                    if not edge_found or "NO EDGE" in response.upper():
                        self.stats["no_edge"] += 1
                        return {"probability": market_price, "confidence": "LOW", "reasoning": "No edge found", "raw": market_price}
                    
                    # Apply edge cap
                    raw_prob = prob
                    if prob is not None:
                        max_edge = EDGE_CAPS.get(confidence, 0.15)
                        current_edge = abs(prob - market_price)
                        if current_edge > max_edge:
                            self.stats["capped"] += 1
                            if prob > market_price:
                                prob = market_price + max_edge
                            else:
                                prob = market_price - max_edge
                    
                    return {"probability": prob, "confidence": confidence, "reasoning": reasoning, "raw": raw_prob}
        except Exception as e:
            return {"probability": None, "confidence": "LOW", "reasoning": f"Error: {e}", "raw": None}
        return {"probability": None, "confidence": "LOW", "reasoning": "No response", "raw": None}
    
    async def scan_market(self, session: aiohttp.ClientSession, market: dict) -> Optional[dict]:
        async with self.semaphore:
            self.stats["scanned"] += 1
            market_id = market["id"]
            question = market["question"]
            
            try:
                prices = json.loads(market["outcome_prices"])
                market_price = float(prices[0])
            except:
                return None
            
            if market_price < 0.02 or market_price > 0.98:
                return None
            
            research = await self.search(session, f"{question} news prediction 2026")
            analysis = await self.analyze(session, question, research, market_price)
            
            if analysis["probability"] is None:
                return None
            
            est_prob = analysis["probability"]
            raw_est = analysis.get("raw", est_prob)
            
            if est_prob > market_price:
                direction = "YES"
                edge = est_prob - market_price
            else:
                direction = "NO"
                edge = market_price - est_prob
            
            if edge < MIN_EDGE:
                return None
            
            self.stats["alpha"] += 1
            
            result = {
                "market_id": market_id,
                "question": question,
                "market_price": market_price,
                "estimated_prob": est_prob,
                "raw_estimate": raw_est,
                "edge": edge,
                "direction": direction,
                "confidence": analysis["confidence"],
                "reasoning": analysis["reasoning"],
                "research_summary": research[:500]
            }
            
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('''INSERT OR REPLACE INTO alpha_scans_v3 VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (market_id, question, market_price, est_prob, raw_est, edge, direction,
                 analysis["confidence"], analysis["reasoning"], research[:500],
                 datetime.now(timezone.utc).isoformat()))
            conn.commit()
            conn.close()
            
            return result
    
    async def run(self, limit: int = None, min_liquidity: float = 100):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        query = f'''
            SELECT id, question, outcome_prices, liquidity 
            FROM markets 
            WHERE liquidity >= {min_liquidity}
            ORDER BY liquidity DESC
        '''
        if limit:
            query += f' LIMIT {limit}'
        
        markets = [{'id': r[0], 'question': r[1], 'outcome_prices': r[2], 'liquidity': r[3]} 
                   for r in c.execute(query).fetchall()]
        conn.close()
        
        print(f"Scanning {len(markets)} markets with V3 scanner...")
        print(f"Edge caps: LOW={EDGE_CAPS['LOW']*100:.0f}%, MEDIUM={EDGE_CAPS['MEDIUM']*100:.0f}%, HIGH={EDGE_CAPS['HIGH']*100:.0f}%")
        print(f"Min edge to report: {MIN_EDGE*100:.0f}%")
        print()
        
        async with aiohttp.ClientSession() as session:
            tasks = [self.scan_market(session, m) for m in markets]
            results = []
            for i, coro in enumerate(asyncio.as_completed(tasks)):
                result = await coro
                if result:
                    results.append(result)
                    print(f"[{i+1}/{len(markets)}] ALPHA: {result['question'][:50]}...")
                    print(f"         {result['direction']} | Edge: {result['edge']*100:.0f}% | Price: {result['market_price']*100:.0f}% -> Est: {result['estimated_prob']*100:.0f}% | Conf: {result['confidence']}")
                elif (i+1) % 25 == 0:
                    print(f"[{i+1}/{len(markets)}] Progress... (alpha: {self.stats['alpha']}, no_edge: {self.stats['no_edge']}, capped: {self.stats['capped']})")
        
        print(f"\n=== STATS ===")
        print(f"Scanned: {self.stats['scanned']}")
        print(f"Alpha found: {self.stats['alpha']} ({self.stats['alpha']/max(1,self.stats['scanned'])*100:.1f}%)")
        print(f"No edge (LLM agreed with market): {self.stats['no_edge']}")
        print(f"Capped (edge reduced): {self.stats['capped']}")
        return results

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, help='Max markets to scan')
    parser.add_argument('--min-liquidity', type=float, default=500)
    args = parser.parse_args()
    
    scanner = AlphaScanner(max_concurrent=4)
    await scanner.run(limit=args.limit, min_liquidity=args.min_liquidity)

if __name__ == "__main__":
    asyncio.run(main())
