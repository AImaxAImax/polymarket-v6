"""
Deep Research Engine — V6 Core Component

Validates alpha opportunities with multi-source web research
and AI-powered analysis.
"""

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote_plus

import httpx

from .config import V6Config, config
from .models import AlphaOpportunity, ResearchResult, SearchResult

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)


class DeepResearcher:
    """
    Deep research engine for validating alpha opportunities.
    
    Runs multiple web searches per opportunity, extracts key facts,
    and uses AI to synthesize findings into probability estimates.
    """
    
    # Rate limits
    SEARXNG_DELAY = 0.5  # seconds between search calls
    OLLAMA_DELAY = 2.0   # seconds between AI calls
    MAX_CONCURRENT = 3   # max parallel opportunity processing
    
    def __init__(self, cfg: V6Config = config):
        self.cfg = cfg
        self._http: Optional[httpx.AsyncClient] = None
        self._search_semaphore = asyncio.Semaphore(1)  # Serialize searches
        self._ollama_semaphore = asyncio.Semaphore(1)  # Serialize AI calls
        self._last_search_time = 0
        self._last_ollama_time = 0
    
    async def __aenter__(self):
        self._http = httpx.AsyncClient(timeout=60)
        return self
    
    async def __aexit__(self, *args):
        if self._http:
            await self._http.aclose()
    
    # === Query Generation ===
    
    def _generate_queries(self, opp: AlphaOpportunity) -> list[str]:
        """Generate search queries for an opportunity."""
        question = opp.question
        
        # Extract key entities (proper nouns, orgs, etc.)
        # Simple heuristic: words starting with capital letters that aren't common
        common_words = {"Will", "What", "When", "Who", "How", "Is", "Are", "The", "A", "An", "If", "Yes", "No"}
        words = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', question)
        entities = [w for w in words if w not in common_words and len(w) > 2]
        
        # Build topic from category or first entity
        topic = opp.category or (entities[0] if entities else question.split()[0])
        key_entity = entities[0] if entities else topic
        
        queries = [
            f'"{question}" latest news',
            f'"{question}" probability analysis',
            f'"{question}" expert prediction',
            f'{topic} odds betting markets prediction',
            f'{key_entity} recent developments news',
        ]
        
        # Add entity-specific queries if we have multiple entities
        if len(entities) > 1:
            queries.extend([
                f'{entities[1]} {entities[0]} news today',
                f'{key_entity} forecast prediction 2025 2026',
            ])
        
        # Add outcome-specific queries
        if "win" in question.lower() or "winner" in question.lower():
            queries.append(f'{key_entity} chances odds polls')
        if "price" in question.lower() or "$" in question:
            queries.append(f'{key_entity} price prediction forecast')
        
        return queries[:10]  # Cap at 10 queries
    
    # === SearXNG Search ===
    
    async def _search(self, query: str) -> list[SearchResult]:
        """Run a single search query via SearXNG."""
        async with self._search_semaphore:
            # Rate limit
            elapsed = time.time() - self._last_search_time
            if elapsed < self.SEARXNG_DELAY:
                await asyncio.sleep(self.SEARXNG_DELAY - elapsed)
            
            try:
                url = f"{self.cfg.searxng_url}/search"
                params = {
                    "q": query,
                    "format": "json",
                    "time_range": "week",  # Focus on recent results
                }
                
                resp = await self._http.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
                
                results = []
                for r in data.get("results", [])[:10]:
                    # Parse date if available
                    pub_date = None
                    if r.get("publishedDate"):
                        try:
                            pub_date = datetime.fromisoformat(r["publishedDate"].replace("Z", "+00:00"))
                        except:
                            pass
                    
                    results.append(SearchResult(
                        title=r.get("title", ""),
                        url=r.get("url", ""),
                        snippet=r.get("content", ""),
                        source=r.get("engine", ""),
                        published_date=pub_date,
                    ))
                
                self._last_search_time = time.time()
                return results
                
            except Exception as e:
                logger.debug(f"Search error for '{query[:30]}...': {e}")
                self._last_search_time = time.time()
                return []
    
    async def _run_all_searches(self, opp: AlphaOpportunity) -> tuple[list[SearchResult], list[str]]:
        """Run all search queries for an opportunity."""
        queries = self._generate_queries(opp)
        all_results = []
        seen_urls = set()
        
        for query in queries:
            results = await self._search(query)
            for r in results:
                if r.url not in seen_urls:
                    seen_urls.add(r.url)
                    all_results.append(r)
        
        return all_results, queries
    
    # === Fact Extraction ===
    
    def _extract_key_facts(self, results: list[SearchResult]) -> list[str]:
        """Extract key facts from search results, prioritizing recent sources."""
        facts = []
        
        # Sort by recency (recent first, then by snippet length)
        sorted_results = sorted(
            results,
            key=lambda r: (
                r.is_recent,  # Recent first
                len(r.snippet) > 50,  # Prefer substantial snippets
            ),
            reverse=True,
        )
        
        for r in sorted_results[:15]:  # Top 15 results
            if r.snippet and len(r.snippet) > 30:
                # Clean up snippet
                fact = r.snippet.strip()
                fact = re.sub(r'\s+', ' ', fact)  # Normalize whitespace
                
                # Add source attribution
                source_name = self._extract_domain(r.url)
                date_str = ""
                if r.published_date:
                    days_ago = (datetime.utcnow() - r.published_date).days
                    if days_ago == 0:
                        date_str = " (today)"
                    elif days_ago == 1:
                        date_str = " (yesterday)"
                    elif days_ago < 7:
                        date_str = f" ({days_ago} days ago)"
                
                facts.append(f"• {fact[:300]} [{source_name}{date_str}]")
        
        return facts[:10]  # Cap at 10 facts
    
    def _extract_domain(self, url: str) -> str:
        """Extract readable domain from URL."""
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc
            # Remove www. prefix
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except:
            return "source"
    
    # === AI Analysis ===
    
    async def _analyze_with_ai(
        self,
        opp: AlphaOpportunity,
        facts: list[str],
    ) -> tuple[str, float]:
        """Use AI to synthesize research and estimate probability."""
        async with self._ollama_semaphore:
            # Rate limit
            elapsed = time.time() - self._last_ollama_time
            if elapsed < self.OLLAMA_DELAY:
                await asyncio.sleep(self.OLLAMA_DELAY - elapsed)
            
            facts_text = "\n".join(facts) if facts else "No recent information found."
            
            prompt = f"""You are a prediction market analyst. Based on the research below, estimate the probability of this outcome.

QUESTION: {opp.question}

RESEARCH FINDINGS:
{facts_text}

CURRENT MARKET PRICE: {opp.market_price:.1%}

INSTRUCTIONS:
1. Analyze the research findings objectively
2. Consider source quality and recency
3. Identify key factors that support or oppose the outcome
4. Provide your probability estimate

FORMAT YOUR RESPONSE AS:
ANALYSIS: [2-3 sentence summary of key findings and reasoning]
PROBABILITY: [number 0-100]"""

            try:
                resp = await self._http.post(
                    f"{self.cfg.ollama_url}/api/generate",
                    json={
                        "model": self.cfg.ollama_model,
                        "prompt": prompt,
                        "stream": False,
                    },
                    timeout=90,
                )
                resp.raise_for_status()
                
                result = resp.json()
                response_text = result.get("response", "").strip()
                
                # Extract summary
                summary_match = re.search(r'ANALYSIS:\s*(.+?)(?=PROBABILITY:|$)', response_text, re.DOTALL)
                summary = summary_match.group(1).strip() if summary_match else response_text[:300]
                
                # Extract probability
                prob_match = re.search(r'PROBABILITY:\s*(\d+(?:\.\d+)?)', response_text)
                if prob_match:
                    prob = float(prob_match.group(1))
                    if prob > 1:
                        prob = prob / 100
                    prob = max(0, min(1, prob))
                else:
                    # Fallback: find any number
                    numbers = re.findall(r'(\d+(?:\.\d+)?)\s*%?', response_text)
                    if numbers:
                        prob = float(numbers[-1])
                        if prob > 1:
                            prob = prob / 100
                        prob = max(0, min(1, prob))
                    else:
                        prob = opp.ai_estimate  # Keep original if no number found
                
                self._last_ollama_time = time.time()
                return summary, prob
                
            except Exception as e:
                logger.error(f"AI analysis error: {e}")
                self._last_ollama_time = time.time()
                return f"Analysis failed: {e}", opp.ai_estimate
    
    # === Main Research Pipeline ===
    
    async def research_opportunity(self, opp: AlphaOpportunity) -> ResearchResult:
        """Run deep research on a single alpha opportunity."""
        start_time = time.time()
        
        logger.info(f"🔍 Researching: {opp.question[:60]}...")
        
        # Run searches
        search_results, queries = await self._run_all_searches(opp)
        logger.debug(f"  Found {len(search_results)} search results from {len(queries)} queries")
        
        # Extract facts
        key_facts = self._extract_key_facts(search_results)
        
        # Count recent sources
        recent_count = sum(1 for r in search_results if r.is_recent)
        
        # Get AI analysis
        summary, post_estimate = await self._analyze_with_ai(opp, key_facts)
        
        # Collect unique source URLs
        sources = list(set(r.url for r in search_results[:20]))
        
        duration = time.time() - start_time
        
        result = ResearchResult(
            opportunity=opp,
            research_summary=summary,
            sources=sources,
            key_facts=key_facts,
            ai_estimate_pre=opp.ai_estimate,
            ai_estimate_post=post_estimate,
            confidence_delta=post_estimate - opp.ai_estimate,
            queries_run=len(queries),
            results_found=len(search_results),
            recent_sources=recent_count,
            research_duration_sec=duration,
        )
        
        logger.info(f"  ✓ {result}")
        return result
    
    async def research_batch(
        self,
        opportunities: list[AlphaOpportunity],
        max_concurrent: int = None,
    ) -> list[ResearchResult]:
        """
        Research multiple opportunities with controlled concurrency.
        
        Args:
            opportunities: List of alpha opportunities to research
            max_concurrent: Max parallel research tasks (default: 3)
        
        Returns:
            List of ResearchResult for each opportunity
        """
        max_concurrent = max_concurrent or self.MAX_CONCURRENT
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def research_with_limit(opp: AlphaOpportunity) -> ResearchResult:
            async with semaphore:
                return await self.research_opportunity(opp)
        
        logger.info(f"Starting deep research on {len(opportunities)} opportunities (max {max_concurrent} concurrent)...")
        
        tasks = [research_with_limit(opp) for opp in opportunities]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out exceptions
        valid_results = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.error(f"Research failed for opportunity {i}: {r}")
            else:
                valid_results.append(r)
        
        # Sort by post-research edge
        valid_results.sort(key=lambda r: r.edge_pct_post, reverse=True)
        
        logger.info(f"Research complete: {len(valid_results)}/{len(opportunities)} successful")
        return valid_results


async def run_research(opportunities: list[AlphaOpportunity]) -> list[ResearchResult]:
    """Convenience function to run deep research."""
    async with DeepResearcher() as researcher:
        return await researcher.research_batch(opportunities)


# === CLI Entry Point ===

if __name__ == "__main__":
    import sys
    from .alpha_scanner import run_scan
    
    async def main():
        # Get top N from command line, default 5
        top_n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
        
        # First, run a quick scan to get opportunities
        print("=" * 60)
        print("STEP 1: Scanning for alpha opportunities...")
        print("=" * 60)
        
        scan_result = await run_scan(max_markets=100)  # Quick scan
        
        if not scan_result.opportunities:
            print("No alpha opportunities found!")
            return
        
        print(f"\nFound {len(scan_result.opportunities)} opportunities")
        
        # Take top N by edge
        top_opps = scan_result.opportunities[:top_n]
        
        print(f"\n" + "=" * 60)
        print(f"STEP 2: Deep research on top {len(top_opps)} opportunities...")
        print("=" * 60)
        
        async with DeepResearcher() as researcher:
            results = await researcher.research_batch(top_opps)
        
        # Print results
        print("\n" + "=" * 60)
        print("RESEARCH RESULTS")
        print("=" * 60)
        
        for i, r in enumerate(results, 1):
            print(f"\n{'─' * 60}")
            print(f"#{i} | {r.opportunity.direction.value} @ {r.opportunity.market_price:.1%}")
            print(f"Question: {r.opportunity.question}")
            print(f"URL: https://polymarket.com/event/{r.opportunity.slug}")
            print(f"\n📊 Probability Shift:")
            print(f"   Pre-research:  {r.ai_estimate_pre:.1%}")
            print(f"   Post-research: {r.ai_estimate_post:.1%}")
            delta_sign = "+" if r.confidence_delta > 0 else ""
            print(f"   Change:        {delta_sign}{r.confidence_delta:.1%}")
            print(f"   Final Edge:    {r.edge_pct_post:.1f}%")
            print(f"\n📝 Summary: {r.research_summary}")
            print(f"\n📰 Key Facts ({r.recent_sources} recent sources):")
            for fact in r.key_facts[:5]:
                print(f"   {fact[:120]}...")
            print(f"\n🔗 Sources: {len(r.sources)} URLs collected")
            print(f"⏱️  Research time: {r.research_duration_sec:.1f}s")
    
    asyncio.run(main())
