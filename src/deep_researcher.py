"""
Phase 2: Deep research module using SearXNG for validation.
Performs parallel searches to validate Phase 1 alpha candidates.
"""
import asyncio
import aiohttp
import json
import re
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from urllib.parse import quote_plus
from tqdm.asyncio import tqdm
import logging

from .database import Database
from .models import AlphaOpportunity

logger = logging.getLogger(__name__)

# Configuration
SEARXNG_ENDPOINT = "http://100.112.76.34:8888"
OLLAMA_ENDPOINT = "http://100.112.76.34:11434"
OLLAMA_MODEL = "qwen2.5:32b"

@dataclass
class SearchResult:
    """Single search result."""
    title: str
    url: str
    snippet: str
    source: str

@dataclass
class ResearchBundle:
    """Bundle of research for a market."""
    market_id: str
    question: str
    current_edge: float
    news_results: List[SearchResult]
    expert_results: List[SearchResult]
    resolution_results: List[SearchResult]


class SearXNGClient:
    """Async SearXNG search client."""
    
    def __init__(self, session: aiohttp.ClientSession,
                 endpoint: str = SEARXNG_ENDPOINT):
        self.session = session
        self.endpoint = endpoint
        self.semaphore: Optional[asyncio.Semaphore] = None
    
    async def search(self, query: str, categories: str = "general",
                    max_results: int = 5) -> List[SearchResult]:
        """Execute a single search query."""
        if self.semaphore:
            async with self.semaphore:
                return await self._do_search(query, categories, max_results)
        return await self._do_search(query, categories, max_results)
    
    async def _do_search(self, query: str, categories: str,
                        max_results: int) -> List[SearchResult]:
        """Execute search request."""
        try:
            params = {
                "q": query,
                "format": "json",
                "categories": categories,
                "engines": "google,bing,duckduckgo",
                "safesearch": 0
            }
            
            async with self.session.get(
                f"{self.endpoint}/search",
                params=params,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    logger.debug(f"SearXNG error {resp.status}")
                    return []
                
                data = await resp.json()
                results = []
                
                for r in data.get('results', [])[:max_results]:
                    results.append(SearchResult(
                        title=r.get('title', ''),
                        url=r.get('url', ''),
                        snippet=r.get('content', ''),
                        source=r.get('engine', 'unknown')
                    ))
                
                return results
                
        except asyncio.TimeoutError:
            logger.debug(f"Search timeout: {query[:50]}")
            return []
        except Exception as e:
            logger.debug(f"Search error: {e}")
            return []


class DeepResearcher:
    """Performs deep research on Phase 1 candidates."""
    
    def __init__(self, session: aiohttp.ClientSession, db: Database,
                 max_concurrent_searches: int = 200,
                 max_concurrent_analysis: int = 20):
        self.session = session
        self.db = db
        self.max_concurrent_searches = max_concurrent_searches
        self.max_concurrent_analysis = max_concurrent_analysis
        self.search_client = SearXNGClient(session)
        self.search_client.semaphore = asyncio.Semaphore(max_concurrent_searches)
        self.analysis_semaphore = asyncio.Semaphore(max_concurrent_analysis)
    
    def _build_queries(self, candidate: AlphaOpportunity) -> Dict[str, str]:
        """Build 3 search queries for a market."""
        # Extract key terms from question
        question = candidate.question
        
        # Simplify question for search
        search_terms = re.sub(r'[^\w\s]', '', question)[:100]
        
        return {
            "news": f"{search_terms} latest news 2024 2025",
            "expert": f"{search_terms} expert analysis prediction forecast",
            "resolution": f"{search_terms} official announcement result outcome"
        }
    
    async def gather_research(self, candidate: AlphaOpportunity) -> ResearchBundle:
        """Gather all research for a candidate market."""
        queries = self._build_queries(candidate)
        
        # Execute 3 searches in parallel
        news_task = self.search_client.search(queries["news"], "news")
        expert_task = self.search_client.search(queries["expert"], "general")
        resolution_task = self.search_client.search(queries["resolution"], "general")
        
        news, expert, resolution = await asyncio.gather(
            news_task, expert_task, resolution_task,
            return_exceptions=True
        )
        
        # Handle any exceptions
        if isinstance(news, Exception):
            news = []
        if isinstance(expert, Exception):
            expert = []
        if isinstance(resolution, Exception):
            resolution = []
        
        return ResearchBundle(
            market_id=candidate.market_id,
            question=candidate.question,
            current_edge=candidate.edge,
            news_results=news,
            expert_results=expert,
            resolution_results=resolution
        )
    
    async def analyze_research(self, bundle: ResearchBundle,
                               original_result: AlphaOpportunity) -> Tuple[str, float, str]:
        """
        Analyze research bundle with Ollama to validate edge.
        
        Returns:
            (research_summary, validated_edge, final_decision)
        """
        async with self.analysis_semaphore:
            return await self._do_analysis(bundle, original_result)
    
    async def _do_analysis(self, bundle: ResearchBundle,
                           original: AlphaOpportunity) -> Tuple[str, float, str]:
        """Execute Ollama analysis."""
        # Build context from research
        context_parts = []
        
        if bundle.news_results:
            context_parts.append("RECENT NEWS:")
            for r in bundle.news_results[:3]:
                context_parts.append(f"- {r.title}: {r.snippet[:200]}")
        
        if bundle.expert_results:
            context_parts.append("\nEXPERT ANALYSIS:")
            for r in bundle.expert_results[:3]:
                context_parts.append(f"- {r.title}: {r.snippet[:200]}")
        
        if bundle.resolution_results:
            context_parts.append("\nRESOLUTION SOURCES:")
            for r in bundle.resolution_results[:3]:
                context_parts.append(f"- {r.title}: {r.snippet[:200]}")
        
        context = "\n".join(context_parts) if context_parts else "No relevant research found."
        
        prompt = f"""You are validating a potential alpha opportunity in a prediction market.

MARKET: {bundle.question}
Current Market Price: {original.market_price:.2%}
Initial AI Estimate: {original.ai_estimate:.2%}
Initial Edge: {(original.ai_estimate - original.market_price):+.2%}
Initial Reasoning: {original.reasoning or "Not provided"}

RESEARCH GATHERED:
{context}

Based on this research, provide your validated analysis:
1. Does the research SUPPORT or CONTRADICT the initial edge estimate?
2. What is your UPDATED probability estimate?
3. Is this a BUY, SKIP, or AVOID?

Respond in EXACTLY this JSON format:
{{"summary": "2-3 sentence summary of key findings", "validated_probability": 0.XX, "decision": "BUY|SKIP|AVOID", "rationale": "brief rationale"}}

Only output the JSON."""

        try:
            payload = {
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.2,
                    "num_predict": 300
                }
            }
            
            async with self.session.post(
                f"{OLLAMA_ENDPOINT}/api/generate",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=90)
            ) as resp:
                if resp.status != 200:
                    return "Analysis failed", original.edge, "SKIP"
                
                data = await resp.json()
                response_text = data.get('response', '')
                
                # Parse response
                return self._parse_analysis(response_text, original)
                
        except Exception as e:
            logger.debug(f"Analysis error: {e}")
            return f"Error: {e}", original.edge, "SKIP"
    
    def _parse_analysis(self, response: str,
                       original: AlphaOpportunity) -> Tuple[str, float, str]:
        """Parse Ollama analysis response."""
        try:
            json_match = re.search(r'\{[^}]+\}', response, re.DOTALL)
            if not json_match:
                return "Parse error", original.edge, "SKIP"
            
            data = json.loads(json_match.group())
            
            summary = data.get('summary', 'No summary')
            validated_prob = float(data.get('validated_probability', original.ai_estimate))
            decision = data.get('decision', 'SKIP').upper()
            rationale = data.get('rationale', '')
            
            # Calculate validated edge
            validated_edge = validated_prob - original.market_price
            
            # Validate decision
            if decision not in ('BUY', 'SKIP', 'AVOID'):
                decision = 'SKIP'
            
            # Build full summary
            full_summary = f"{summary} Rationale: {rationale}"[:1000]
            
            return full_summary, validated_edge, decision
            
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.debug(f"Parse error: {e}")
            return f"Parse error: {e}", original.edge, "SKIP"


class Phase2Runner:
    """Orchestrates Phase 2 deep research."""
    
    def __init__(self, db: Database,
                 max_concurrent_searches: int = 200,
                 max_concurrent_analysis: int = 20):
        self.db = db
        self.max_concurrent_searches = max_concurrent_searches
        self.max_concurrent_analysis = max_concurrent_analysis
        self.researched = 0
        self.buy_signals = 0
        self.skip_signals = 0
        self.avoid_signals = 0
    
    async def run(self, min_edge: float = 0.05) -> Dict[str, Any]:
        """
        Run Phase 2 on all Phase 1 candidates.
        
        Args:
            min_edge: Minimum edge from Phase 1 to include
            
        Returns:
            Statistics dict
        """
        start_time = datetime.utcnow()
        
        # Get candidates
        candidates = self.db.get_phase1_candidates(min_edge=min_edge)
        if not candidates:
            print("❌ No Phase 1 candidates found. Run Phase 1 first.")
            return {'error': 'No candidates'}
        
        print(f"🔬 Found {len(candidates)} Phase 1 candidates for deep research")
        
        connector = aiohttp.TCPConnector(
            limit=self.max_concurrent_searches * 2,
            limit_per_host=100
        )
        
        async with aiohttp.ClientSession(connector=connector) as session:
            researcher = DeepResearcher(
                session, self.db,
                max_concurrent_searches=self.max_concurrent_searches,
                max_concurrent_analysis=self.max_concurrent_analysis
            )
            
            # Process each candidate
            print(f"🔍 Starting deep research with {self.max_concurrent_searches} concurrent searches...")
            
            async def process_candidate(candidate: ScanResult):
                """Process a single candidate through research + analysis."""
                try:
                    # Gather research
                    bundle = await researcher.gather_research(candidate)
                    
                    # Analyze with Ollama
                    summary, validated_edge, decision = await researcher.analyze_research(
                        bundle, candidate
                    )
                    
                    # Save to database
                    self.db.update_research(
                        market_id=candidate.market_id,
                        research_summary=summary,
                        validated_edge=validated_edge,
                        final_decision=decision
                    )
                    
                    self.researched += 1
                    
                    if decision == 'BUY':
                        self.buy_signals += 1
                    elif decision == 'SKIP':
                        self.skip_signals += 1
                    else:
                        self.avoid_signals += 1
                        
                except Exception as e:
                    logger.error(f"Error processing {candidate.market_id}: {e}")
            
            # Run all candidates with progress
            tasks = [process_candidate(c) for c in candidates]
            
            for coro in tqdm.as_completed(tasks, total=len(tasks), desc="Phase 2 Research"):
                await coro
        
        elapsed = (datetime.utcnow() - start_time).total_seconds()
        
        stats = {
            'total_candidates': len(candidates),
            'researched': self.researched,
            'buy_signals': self.buy_signals,
            'skip_signals': self.skip_signals,
            'avoid_signals': self.avoid_signals,
            'elapsed_seconds': elapsed,
            'candidates_per_minute': (self.researched / elapsed) * 60 if elapsed > 0 else 0
        }
        
        print(f"\n✅ Phase 2 Complete!")
        print(f"   Researched: {self.researched}/{len(candidates)}")
        print(f"   BUY signals: {self.buy_signals}")
        print(f"   SKIP signals: {self.skip_signals}")
        print(f"   AVOID signals: {self.avoid_signals}")
        print(f"   Time: {elapsed:.1f}s ({stats['candidates_per_minute']:.1f}/min)")
        
        return stats


async def run_phase2(db_path: str = "data/scans.db",
                     max_concurrent_searches: int = 200,
                     max_concurrent_analysis: int = 20,
                     min_edge: float = 0.05) -> Dict[str, Any]:
    """
    Run Phase 2 deep research.
    
    Args:
        db_path: Path to SQLite database
        max_concurrent_searches: Number of concurrent SearXNG searches
        max_concurrent_analysis: Number of concurrent Ollama analysis calls
        min_edge: Minimum edge threshold from Phase 1
        
    Returns:
        Research statistics
    """
    db = Database(db_path)
    runner = Phase2Runner(
        db,
        max_concurrent_searches=max_concurrent_searches,
        max_concurrent_analysis=max_concurrent_analysis
    )
    return await runner.run(min_edge=min_edge)
