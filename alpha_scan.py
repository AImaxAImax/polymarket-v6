#!/usr/bin/env python3
"""Alpha Scanner: Research-first approach using SearXNG + Ollama

Fixes:
- Clearer prompt specifying YES probability
- Sanity check for reasoning/probability contradictions
- Better search queries
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

class AlphaScanner:
    def __init__(self, max_concurrent: int = 4):
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.setup_db()
    
    def setup_db(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS alpha_scans (
            market_id TEXT PRIMARY KEY,
            question TEXT,
            market_price REAL,
            estimated_prob REAL,
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
        """Search web via SearXNG."""
        try:
            params = {"q": query, "format": "json", "engines": "google,bing,duckduckgo"}
            async with session.get(SEARXNG_URL, params=params, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("results", [])[:5]
                    return "\n".join([f"- {r.get('title')}: {r.get('content', '')[:200]}" for r in results])
        except Exception as e:
            return f"Search error: {e}"
        return "No results"
    
    async def analyze(self, session: aiohttp.ClientSession, question: str, research: str, market_price: float) -> dict:
        """Use Ollama to estimate probability with research context."""
        # FIXED: Much clearer prompt about YES probability
        prompt = f"""You are a prediction market analyst. Estimate the probability that the answer to this question is YES.

QUESTION: {question}

The market currently prices YES at {market_price:.1%}. Based on the research below, what do YOU think the TRUE probability of YES is?

RESEARCH:
{research}

IMPORTANT: 
- If the event is LIKELY to happen, probability should be HIGH (e.g., 70-95%)
- If the event is UNLIKELY to happen, probability should be LOW (e.g., 5-30%)
- Your reasoning MUST match your probability estimate

Respond in this EXACT format:
PROBABILITY: [number]%
CONFIDENCE: [LOW/MEDIUM/HIGH]
REASONING: [1-2 sentences explaining WHY you chose that probability]
"""
        try:
            payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}
            async with session.post(OLLAMA_URL, json=payload, timeout=60) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    response = data.get("response", "")
                    
                    # Parse response
                    prob_match = re.search(r'PROBABILITY:\s*(\d+)%', response)
                    conf_match = re.search(r'CONFIDENCE:\s*(LOW|MEDIUM|HIGH)', response, re.I)
                    reason_match = re.search(r'REASONING:\s*(.+)', response, re.S)
                    
                    prob = int(prob_match.group(1)) / 100 if prob_match else None
                    reasoning = reason_match.group(1).strip()[:500] if reason_match else response[:500]
                    
                    # SANITY CHECK: Detect contradictions
                    if prob is not None:
                        unlikely_words = ['unlikely', 'improbable', 'doubtful', 'won\'t', 'will not', 'no chance', 'impossible']
                        likely_words = ['likely', 'probable', 'will', 'expected', 'certain', 'definitely']
                        
                        reasoning_lower = reasoning.lower()
                        has_unlikely = any(w in reasoning_lower for w in unlikely_words)
                        has_likely = any(w in reasoning_lower for w in likely_words)
                        
                        # If reasoning says unlikely but prob is high, flip it
                        if has_unlikely and not has_likely and prob > 0.5:
                            prob = 1 - prob
                        # If reasoning says likely but prob is low, flip it
                        elif has_likely and not has_unlikely and prob < 0.5:
                            prob = 1 - prob
                    
                    return {
                        "probability": prob,
                        "confidence": conf_match.group(1).upper() if conf_match else "LOW",
                        "reasoning": reasoning
                    }
        except Exception as e:
            return {"probability": None, "confidence": "LOW", "reasoning": f"Error: {e}"}
        return {"probability": None, "confidence": "LOW", "reasoning": "No response"}
    
    async def scan_market(self, session: aiohttp.ClientSession, market: dict) -> Optional[dict]:
        """Scan a single market for alpha."""
        async with self.semaphore:
            market_id = market["id"]
            question = market["question"]
            
            # Parse market price (YES outcome)
            try:
                prices = json.loads(market["outcome_prices"])
                market_price = float(prices[0])
            except:
                return None
            
            # Skip extreme prices (no edge possible)
            if market_price < 0.02 or market_price > 0.98:
                return None
            
            # Web research - better query
            search_query = f"{question} latest news prediction"
            research = await self.search(session, search_query)
            
            # LLM analysis
            analysis = await self.analyze(session, question, research, market_price)
            
            if analysis["probability"] is None:
                return None
            
            # Calculate edge
            est_prob = analysis["probability"]
            
            # Determine direction and edge
            if est_prob > market_price:
                direction = "YES"
                edge = est_prob - market_price
            else:
                direction = "NO"
                edge = market_price - est_prob
            
            return {
                "market_id": market_id,
                "question": question,
                "market_price": market_price,
                "estimated_prob": est_prob,
                "edge": edge,
                "direction": direction,
                "confidence": analysis["confidence"],
                "reasoning": analysis["reasoning"],
                "research_summary": research[:500]
            }
    
    async def run(self, limit: Optional[int] = None, min_liquidity: float = 1000, min_edge: float = 0.10):
        """Run alpha scan on all markets."""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        query = f'''SELECT id, question, outcome_prices, liquidity FROM markets 
                    WHERE liquidity >= {min_liquidity} ORDER BY liquidity DESC'''
        if limit:
            query += f" LIMIT {limit}"
        
        markets = [dict(zip(['id','question','outcome_prices','liquidity'], row)) 
                   for row in c.execute(query).fetchall()]
        conn.close()
        
        print(f"\n🎯 Scanning {len(markets)} markets for alpha...")
        print(f"   Concurrent: {self.max_concurrent} | Min liquidity: ${min_liquidity:,.0f} | Min edge: {min_edge:.0%}")
        
        async with aiohttp.ClientSession() as session:
            tasks = [self.scan_market(session, m) for m in markets]
            
            results = []
            alpha_count = 0
            
            for i, coro in enumerate(asyncio.as_completed(tasks)):
                result = await coro
                if result and result["edge"] >= min_edge:
                    alpha_count += 1
                    results.append(result)
                    print(f"🎯 ALPHA: {result['direction']} {result['question'][:50]}... "
                          f"Edge: {result['edge']:.1%} @ {result['market_price']:.1%} [{result['confidence']}]")
                    
                    # Save to DB
                    conn = sqlite3.connect(DB_PATH)
                    conn.execute('''INSERT OR REPLACE INTO alpha_scans VALUES (?,?,?,?,?,?,?,?,?,?)''',
                        (result['market_id'], result['question'], result['market_price'],
                         result['estimated_prob'], result['edge'], result['direction'],
                         result['confidence'], result['reasoning'], result['research_summary'],
                         datetime.now(timezone.utc).isoformat()))
                    conn.commit()
                    conn.close()
                
                if (i+1) % 50 == 0:
                    print(f"   Progress: {i+1}/{len(markets)} | Alpha found: {alpha_count}")
        
        print(f"\n✅ Scan complete! Found {alpha_count} opportunities with {min_edge:.0%}+ edge")
        return results

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Max markets to scan")
    parser.add_argument("--concurrent", type=int, default=8, help="Concurrent scans")
    parser.add_argument("--min-liquidity", type=float, default=1000, help="Min liquidity")
    parser.add_argument("--min-edge", type=float, default=0.10, help="Min edge (0.10 = 10%)")
    args = parser.parse_args()
    
    scanner = AlphaScanner(max_concurrent=args.concurrent)
    asyncio.run(scanner.run(limit=args.limit, min_liquidity=args.min_liquidity, min_edge=args.min_edge))
