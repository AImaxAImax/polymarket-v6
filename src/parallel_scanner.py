"""
Phase 1: Parallel async market scanner using Ollama.
Scans ALL markets with high concurrency for quick alpha detection.
"""
import asyncio
import aiohttp
import json
import re
from datetime import datetime
from typing import List, Dict, Any, Optional, AsyncIterator
from dataclasses import dataclass
from tqdm.asyncio import tqdm
import logging

from .database import Database
from .models import ScanResult

logger = logging.getLogger(__name__)

# Configuration
OLLAMA_ENDPOINT = "http://100.112.76.34:11434"
OLLAMA_MODEL = "qwen2.5:32b"
POLYMARKET_API = "https://gamma-api.polymarket.com"

@dataclass
class Market:
    """Polymarket market data."""
    id: str
    question: str
    outcome_prices: List[float]
    volume: float
    liquidity: float
    end_date: Optional[str] = None

class PolymarketClient:
    """Async client for Polymarket API."""
    
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.base_url = POLYMARKET_API
    
    async def fetch_all_markets(self, limit: int = 100, active_only: bool = True, max_markets: Optional[int] = None) -> List[Market]:
        """Fetch markets from Polymarket API.
        
        Args:
            limit: Items per API page (default 100)
            active_only: Only fetch active markets
            max_markets: Stop after fetching this many markets (None = fetch all)
        """
        markets = []
        offset = 0
        
        while True:
            # Early exit if we have enough markets
            if max_markets and len(markets) >= max_markets:
                return markets[:max_markets]
            try:
                params = {
                    "limit": limit,
                    "offset": offset,
                    "active": str(active_only).lower(),
                    "closed": "false"
                }
                async with self.session.get(
                    f"{self.base_url}/markets",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status != 200:
                        logger.error(f"API error: {resp.status}")
                        break
                    
                    data = await resp.json()
                    if not data:
                        break
                    
                    for m in data:
                        try:
                            # Parse outcome prices
                            prices = []
                            if 'outcomePrices' in m:
                                prices = json.loads(m['outcomePrices']) if isinstance(m['outcomePrices'], str) else m['outcomePrices']
                            elif 'outcomes' in m:
                                prices = [float(o.get('price', 0.5)) for o in m.get('outcomes', [])]
                            
                            if not prices:
                                prices = [0.5, 0.5]
                            
                            markets.append(Market(
                                id=m.get('id', m.get('conditionId', '')),
                                question=m.get('question', ''),
                                outcome_prices=[float(p) for p in prices],
                                volume=float(m.get('volume', 0) or 0),
                                liquidity=float(m.get('liquidity', 0) or 0),
                                end_date=m.get('endDate')
                            ))
                        except (KeyError, ValueError, TypeError) as e:
                            logger.debug(f"Skipping market: {e}")
                            continue
                    
                    if len(data) < limit:
                        break
                    
                    offset += limit
                    
            except asyncio.TimeoutError:
                logger.error(f"Timeout fetching markets at offset {offset}")
                break
            except Exception as e:
                logger.error(f"Error fetching markets: {e}")
                break
        
        return markets

class OllamaScanner:
    """Async Ollama scanner for market probability estimation."""
    
    def __init__(self, session: aiohttp.ClientSession, 
                 endpoint: str = OLLAMA_ENDPOINT,
                 model: str = OLLAMA_MODEL):
        self.session = session
        self.endpoint = endpoint
        self.model = model
        self.semaphore: Optional[asyncio.Semaphore] = None
    
    def _build_prompt(self, market: Market) -> str:
        """Build the analysis prompt for a market."""
        yes_price = market.outcome_prices[0] if market.outcome_prices else 0.5
        
        return f"""Analyze this prediction market and estimate the TRUE probability:

Question: {market.question}
Current YES Price: {yes_price:.2%}
Volume: ${market.volume:,.0f}
Liquidity: ${market.liquidity:,.0f}

Consider:
1. Base rates for similar events
2. Current information/context
3. Time until resolution
4. Market biases

Respond in EXACTLY this JSON format:
{{"probability": 0.XX, "confidence": 0.X, "reasoning": "brief explanation"}}

Only output the JSON, nothing else."""

    async def scan_market(self, market: Market) -> Optional[ScanResult]:
        """Scan a single market with Ollama."""
        if self.semaphore:
            async with self.semaphore:
                return await self._do_scan(market)
        return await self._do_scan(market)
    
    async def _do_scan(self, market: Market) -> Optional[ScanResult]:
        """Execute the actual scan."""
        prompt = self._build_prompt(market)
        
        try:
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "num_predict": 200
                }
            }
            
            async with self.session.post(
                f"{self.endpoint}/api/generate",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                if resp.status != 200:
                    logger.debug(f"Ollama error {resp.status} for {market.id}")
                    return None
                
                data = await resp.json()
                response_text = data.get('response', '')
                
                # Parse JSON response
                result = self._parse_response(response_text, market)
                return result
                
        except asyncio.TimeoutError:
            logger.debug(f"Timeout scanning {market.id}")
            return None
        except Exception as e:
            logger.debug(f"Error scanning {market.id}: {e}")
            return None
    
    def _parse_response(self, response: str, market: Market) -> Optional[ScanResult]:
        """Parse Ollama response into ScanResult."""
        try:
            # Extract JSON from response
            json_match = re.search(r'\{[^}]+\}', response, re.DOTALL)
            if not json_match:
                return None
            
            data = json.loads(json_match.group())
            
            probability = float(data.get('probability', 0.5))
            confidence = float(data.get('confidence', 0.5))
            reasoning = data.get('reasoning', '')
            
            # Clamp values
            probability = max(0.01, min(0.99, probability))
            confidence = max(0.1, min(1.0, confidence))
            
            # Calculate edge
            market_price = market.outcome_prices[0] if market.outcome_prices else 0.5
            edge = probability - market_price
            
            return ScanResult(
                market_id=market.id,
                question=market.question,
                market_price=market_price,
                ai_estimate=probability,
                edge=edge,
                confidence=confidence,
                reasoning=reasoning[:500],  # Truncate
                scanned_at=datetime.utcnow().isoformat(),
                phase=1
            )
            
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.debug(f"Parse error: {e}")
            return None

class ParallelScanner:
    """Orchestrates parallel market scanning."""
    
    def __init__(self, db: Database, max_concurrent: int = 50):
        self.db = db
        self.max_concurrent = max_concurrent
        self.scanned = 0
        self.errors = 0
        self.candidates = 0
    
    async def scan_all(self, market_limit: Optional[int] = None, 
                       min_edge_threshold: float = 0.05) -> Dict[str, Any]:
        """
        Scan all markets in parallel.
        
        Args:
            market_limit: Optional limit on number of markets to scan
            min_edge_threshold: Edge threshold for counting candidates
            
        Returns:
            Statistics dict
        """
        start_time = datetime.utcnow()
        
        connector = aiohttp.TCPConnector(limit=self.max_concurrent * 2, limit_per_host=self.max_concurrent)
        timeout = aiohttp.ClientTimeout(total=300, connect=10)
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            # Fetch markets
            print(f"📡 Fetching markets from Polymarket...", flush=True)
            pm_client = PolymarketClient(session)
            markets = await pm_client.fetch_all_markets(max_markets=market_limit)
            
            print(f"📊 Found {len(markets)} markets to scan")
            
            # Setup scanner with semaphore
            scanner = OllamaScanner(session)
            scanner.semaphore = asyncio.Semaphore(self.max_concurrent)
            
            # Scan all markets in parallel with progress bar
            print(f"🔍 Scanning with {self.max_concurrent} concurrent Ollama calls...")
            
            tasks = [scanner.scan_market(m) for m in markets]
            results = []
            
            for coro in tqdm.as_completed(tasks, total=len(tasks), desc="Phase 1 Scan"):
                result = await coro
                if result:
                    results.append(result)
                    self.scanned += 1
                    
                    # Save to database
                    self.db.upsert_scan(result)
                    
                    if abs(result.edge) >= min_edge_threshold:
                        self.candidates += 1
                else:
                    self.errors += 1
        
        elapsed = (datetime.utcnow() - start_time).total_seconds()
        
        stats = {
            'total_markets': len(markets),
            'scanned': self.scanned,
            'errors': self.errors,
            'candidates': self.candidates,
            'elapsed_seconds': elapsed,
            'markets_per_minute': (self.scanned / elapsed) * 60 if elapsed > 0 else 0
        }
        
        print(f"\n✅ Phase 1 Complete!")
        print(f"   Scanned: {self.scanned}/{len(markets)}")
        print(f"   Candidates (edge ≥ {min_edge_threshold:.0%}): {self.candidates}")
        print(f"   Time: {elapsed:.1f}s ({stats['markets_per_minute']:.0f}/min)")
        
        return stats


async def run_phase1(db_path: str = "data/scans.db",
                     max_concurrent: int = 50,
                     market_limit: Optional[int] = None) -> Dict[str, Any]:
    """
    Run Phase 1 parallel scan.
    
    Args:
        db_path: Path to SQLite database
        max_concurrent: Number of concurrent Ollama calls
        market_limit: Optional limit for testing
        
    Returns:
        Scan statistics
    """
    db = Database(db_path)
    scanner = ParallelScanner(db, max_concurrent=max_concurrent)
    return await scanner.scan_all(market_limit=market_limit)
