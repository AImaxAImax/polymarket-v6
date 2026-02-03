#!/usr/bin/env python3
"""Alpha Validator: Second-pass verification using a smarter model

Checks:
1. Constitutional/legal eligibility
2. Sports: verify direction matches research sentiment
3. Consistency: reasoning matches direction
4. Red flags: term limits, ineligibility, contradictions
"""
import asyncio
import aiohttp
import sqlite3
import json
import re
from datetime import datetime, timezone

SEARXNG_URL = "http://100.112.76.34:8888/search"
OLLAMA_URL = "http://100.112.76.34:11434/api/generate"
OLLAMA_MODEL = "deepseek-r1:32b"  # Better reasoning model for validation
DB_PATH = "data/markets.db"

class AlphaValidator:
    def __init__(self):
        self.setup_db()
    
    def setup_db(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS validated_alpha (
            market_id TEXT PRIMARY KEY,
            question TEXT,
            direction TEXT,
            edge REAL,
            market_price REAL,
            estimated_prob REAL,
            validation_status TEXT,
            validation_reasoning TEXT,
            red_flags TEXT,
            final_recommendation TEXT,
            validated_at TEXT
        )''')
        conn.commit()
        conn.close()
    
    async def deep_research(self, session: aiohttp.ClientSession, question: str) -> str:
        """More thorough research with multiple queries."""
        queries = [
            question.replace("Will ", "").replace("?", "") + " latest news",
            question.replace("Will ", "").replace("?", "") + " odds prediction",
            question.replace("Will ", "").replace("?", "") + " eligibility rules requirements",
        ]
        
        all_results = []
        for q in queries:
            try:
                params = {"q": q, "format": "json"}
                async with session.get(SEARXNG_URL, params=params, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results = data.get("results", [])[:3]
                        for r in results:
                            all_results.append(f"- {r.get('title')}: {r.get('content', '')[:200]}")
            except:
                pass
        
        return "\n".join(all_results[:8])  # Top 8 results
    
    async def validate(self, session: aiohttp.ClientSession, market: dict) -> dict:
        """Validate an alpha pick with deeper analysis."""
        question = market['question']
        direction = market['direction']
        edge = market['edge']
        price = market['market_price']
        est = market['estimated_prob']
        original_reasoning = market['reasoning']
        
        # Deep research
        research = await self.deep_research(session, question)
        
        prompt = f"""You are a prediction market validator. Your job is to CHECK if an alpha signal is valid or a false positive.

ORIGINAL SIGNAL:
- Question: {question}
- Direction: {direction} (we think this outcome is more likely than market)
- Market price: {price:.1%}
- Our estimate: {est:.1%}
- Edge claimed: {edge:.1%}
- Original reasoning: {original_reasoning[:300]}

NEW RESEARCH:
{research}

== VALIDATION CHECKS ==
1. ELIGIBILITY: Is there any legal, constitutional, or rule-based reason this can't happen?
   - Term limits (e.g., 22nd Amendment limits presidents to 2 terms)
   - Age requirements
   - Citizenship requirements
   - League/competition rules

2. CONTRADICTION: Does the research CONTRADICT our direction?
   - If we say YES but research says opponent is favored → RED FLAG
   - If we say NO but research says this team/person is strong → RED FLAG

3. REASONING: Does the original reasoning make sense given the research?

4. EDGE SIZE: Is the claimed edge reasonable?
   - >30% edge should require very strong evidence
   - >50% edge is almost always wrong

== RESPOND ==
STATUS: [VALID / INVALID / WEAK]
RED_FLAGS: [List any issues, or "None"]
REASONING: [1-2 sentences explaining your validation]
RECOMMENDATION: [BET / SKIP / NEEDS_MORE_INFO]
"""
        
        try:
            payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}
            async with session.post(OLLAMA_URL, json=payload, timeout=120) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    response = data.get("response", "")
                    
                    # Parse response
                    status_match = re.search(r'STATUS:\s*(VALID|INVALID|WEAK)', response, re.I)
                    flags_match = re.search(r'RED_FLAGS:\s*(.+?)(?=REASONING:|$)', response, re.S)
                    reason_match = re.search(r'REASONING:\s*(.+?)(?=RECOMMENDATION:|$)', response, re.S)
                    rec_match = re.search(r'RECOMMENDATION:\s*(BET|SKIP|NEEDS_MORE_INFO)', response, re.I)
                    
                    return {
                        "status": status_match.group(1).upper() if status_match else "UNKNOWN",
                        "red_flags": flags_match.group(1).strip()[:500] if flags_match else "",
                        "reasoning": reason_match.group(1).strip()[:500] if reason_match else response[:500],
                        "recommendation": rec_match.group(1).upper() if rec_match else "SKIP"
                    }
        except Exception as e:
            return {"status": "ERROR", "red_flags": str(e), "reasoning": "", "recommendation": "SKIP"}
        
        return {"status": "UNKNOWN", "red_flags": "", "reasoning": "No response", "recommendation": "SKIP"}
    
    async def run(self, min_edge: float = 0.08):
        """Validate all alpha picks."""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Get alpha picks to validate
        picks = c.execute('''
            SELECT market_id, question, direction, edge, market_price, estimated_prob, reasoning
            FROM alpha_scans_v3 WHERE edge >= ?
            ORDER BY edge DESC
        ''', (min_edge,)).fetchall()
        conn.close()
        
        print(f"Validating {len(picks)} alpha picks...")
        print(f"Using {OLLAMA_MODEL} for deeper reasoning\n")
        
        results = {"VALID": [], "INVALID": [], "WEAK": [], "UNKNOWN": []}
        
        async with aiohttp.ClientSession() as session:
            for i, (mid, q, d, e, p, est, r) in enumerate(picks):
                print(f"[{i+1}/{len(picks)}] {q[:50]}...")
                
                market = {
                    "market_id": mid,
                    "question": q,
                    "direction": d,
                    "edge": e,
                    "market_price": p,
                    "estimated_prob": est,
                    "reasoning": r
                }
                
                validation = await self.validate(session, market)
                
                print(f"    Status: {validation['status']} | Rec: {validation['recommendation']}")
                if validation['red_flags'] and validation['red_flags'] != 'None':
                    print(f"    Red flags: {validation['red_flags'][:100]}")
                
                results[validation['status']].append(market)
                
                # Save to DB
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute('''INSERT OR REPLACE INTO validated_alpha VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                    (mid, q, d, e, p, est, 
                     validation['status'], validation['reasoning'],
                     validation['red_flags'], validation['recommendation'],
                     datetime.now(timezone.utc).isoformat()))
                conn.commit()
                conn.close()
        
        print(f"\n{'='*60}")
        print(f"VALIDATION COMPLETE")
        print(f"{'='*60}")
        print(f"VALID (BET): {len(results['VALID'])}")
        print(f"INVALID (SKIP): {len(results['INVALID'])}")
        print(f"WEAK (CAUTION): {len(results['WEAK'])}")
        print(f"UNKNOWN: {len(results['UNKNOWN'])}")
        
        return results

async def main():
    validator = AlphaValidator()
    await validator.run()

if __name__ == "__main__":
    asyncio.run(main())
