"""Research engine using SearXNG for parallel market research."""
import asyncio
import aiohttp
from typing import List, Dict, Optional
from datetime import datetime
import logging
import urllib.parse

from .models import Market, ResearchResult
from .database import Database

logger = logging.getLogger(__name__)


class ResearchEngine:
    """Parallel research engine using SearXNG."""
    
    def __init__(self, 
                 searxng_url: str = "http://100.112.76.34:8888",
                 max_concurrent: int = 200):
        self.searxng_url = searxng_url.rstrip("/")
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        )
        return self
    
    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()
    
    async def research_markets(self, markets: List[Market], db: Database) -> List[ResearchResult]:
        """
        Research multiple markets in parallel.
        Updates database with results as they complete.
        """
        tasks = [self._research_market(market, db) for market in markets]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out exceptions
        valid_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Research failed for {markets[i].id}: {result}")
            elif result:
                valid_results.append(result)
        
        return valid_results
    
    async def _research_market(self, market: Market, db: Database) -> Optional[ResearchResult]:
        """Research a single market with 3 search queries."""
        try:
            # Extract key terms from question
            question = market.question
            
            # Create search queries
            queries = self._generate_queries(question, market.category)
            
            # Execute searches in parallel
            search_tasks = [
                self._search(queries[0]),  # News search
                self._search(queries[1]),  # Expert search
                self._search(queries[2]),  # Resolution source search
            ]
            
            results = await asyncio.gather(*search_tasks, return_exceptions=True)
            
            # Build research result
            research = ResearchResult(
                market_id=market.id,
                researched_at=datetime.utcnow().isoformat()
            )
            
            if not isinstance(results[0], Exception):
                research.news_results = results[0] or []
            if not isinstance(results[1], Exception):
                research.expert_results = results[1] or []
            if not isinstance(results[2], Exception):
                research.source_results = results[2] or []
            
            # Compile summary
            summary = research.compile_summary()
            
            # Update database
            db.update_research(market.id, summary)
            
            logger.debug(f"Researched market {market.id}: {len(research.news_results)} news, "
                        f"{len(research.expert_results)} expert, {len(research.source_results)} sources")
            
            return research
            
        except Exception as e:
            logger.error(f"Research error for {market.id}: {e}")
            return None
    
    def _generate_queries(self, question: str, category: Optional[str] = None) -> List[str]:
        """Generate 3 search queries for a market question."""
        # Clean up question
        question = question.strip()
        
        # Remove common prefixes
        for prefix in ["Will ", "Is ", "Does ", "Can ", "Has ", "Are "]:
            if question.startswith(prefix):
                question = question[len(prefix):]
                break
        
        # Remove question mark
        question = question.rstrip("?")
        
        # Base terms
        base_terms = question[:100]  # Limit length
        
        queries = [
            # News query - recent events
            f"{base_terms} news 2025 2026",
            
            # Expert/analysis query
            f"{base_terms} analysis prediction expert",
            
            # Resolution source query
            f"{base_terms} official announcement source",
        ]
        
        return queries
    
    async def _search(self, query: str) -> List[Dict]:
        """Execute a single search query."""
        async with self.semaphore:
            try:
                # SearXNG JSON API
                url = f"{self.searxng_url}/search"
                params = {
                    "q": query,
                    "format": "json",
                    "engines": "google,bing,duckduckgo",
                    "language": "en",
                }
                
                async with self.session.get(url, params=params) as resp:
                    if resp.status != 200:
                        logger.warning(f"Search failed with status {resp.status}")
                        return []
                    
                    data = await resp.json()
                    results = data.get("results", [])
                    
                    # Extract relevant fields
                    parsed = []
                    for r in results[:10]:  # Top 10 results
                        parsed.append({
                            "title": r.get("title", ""),
                            "url": r.get("url", ""),
                            "content": r.get("content", ""),
                            "engine": r.get("engine", ""),
                        })
                    
                    return parsed
                    
            except asyncio.TimeoutError:
                logger.warning(f"Search timeout for query: {query[:50]}...")
                return []
            except Exception as e:
                logger.error(f"Search error: {e}")
                return []


async def research_markets(markets: List[Market], db: Database,
                          searxng_url: str = "http://100.112.76.34:8888",
                          max_concurrent: int = 200) -> List[ResearchResult]:
    """Convenience function to research markets."""
    async with ResearchEngine(searxng_url, max_concurrent) as engine:
        return await engine.research_markets(markets, db)
