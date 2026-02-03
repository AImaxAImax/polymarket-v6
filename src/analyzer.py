"""LLM-based market analyzer using Ollama."""
import asyncio
import aiohttp
import json
import re
from typing import List, Optional, Tuple
from datetime import datetime
import logging

from .models import Market, Signal
from .database import Database

logger = logging.getLogger(__name__)


class Analyzer:
    """LLM-based market analyzer using Ollama."""
    
    SYSTEM_PROMPT = """You are an expert prediction market analyst. Your task is to estimate the probability of events based on research data and market context.

For each market, you will receive:
1. The question being asked
2. Current market prices (YES/NO)
3. Research summary with recent news and analysis

Your job is to:
1. Analyze the research objectively
2. Estimate the TRUE probability of the YES outcome (0.0 to 1.0)
3. Assess your confidence in this estimate (0.0 to 1.0)
4. Provide brief reasoning

Output ONLY valid JSON in this exact format:
{
    "probability": 0.XX,
    "confidence": 0.XX,
    "reasoning": "Brief 1-2 sentence explanation"
}

Guidelines:
- Be calibrated: if you say 70%, it should happen 70% of the time
- High confidence (>0.8) only when research strongly supports a conclusion
- Low confidence (<0.5) when research is sparse or contradictory
- Consider base rates and historical patterns
- Don't anchor too heavily on current market price"""

    def __init__(self,
                 ollama_url: str = "http://100.112.76.34:11434",
                 model: str = "qwen2.5:32b",
                 max_concurrent: int = 10):
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=120)  # LLM can be slow
        )
        return self
    
    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()
    
    async def analyze_markets(self, markets: List[Market], db: Database) -> List[Signal]:
        """Analyze multiple markets and update database."""
        tasks = [self._analyze_market(market, db) for market in markets]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        signals = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Analysis failed for {markets[i].id}: {result}")
            elif result:
                signals.append(result)
        
        return signals
    
    async def _analyze_market(self, market: Market, db: Database) -> Optional[Signal]:
        """Analyze a single market with LLM."""
        async with self.semaphore:
            try:
                # Build prompt with research context
                prompt = self._build_prompt(market)
                
                # Call Ollama
                response = await self._call_ollama(prompt)
                
                if not response:
                    return None
                
                # Parse response
                analysis = self._parse_response(response)
                
                if not analysis:
                    logger.warning(f"Failed to parse analysis for {market.id}")
                    return None
                
                probability = analysis["probability"]
                confidence = analysis["confidence"]
                reasoning = analysis["reasoning"]
                
                # Calculate edge
                market_prob = market.yes_price or 0.5
                edge = probability - market_prob
                
                # Determine signal
                signal = self._determine_signal(edge, confidence, market)
                
                # Calculate recommended size based on liquidity
                rec_size = self._calculate_size(market.liquidity, edge, confidence)
                
                # Update database
                db.update_analysis(
                    market.id,
                    probability=probability,
                    confidence=confidence,
                    reasoning=reasoning,
                    edge=edge,
                    signal=signal,
                    recommended_size=rec_size
                )
                
                logger.debug(f"Analyzed {market.id}: prob={probability:.2f}, "
                           f"edge={edge:+.2%}, signal={signal}")
                
                return Signal(
                    market_id=market.id,
                    signal=signal,
                    edge=edge,
                    confidence=confidence,
                    recommended_size=rec_size,
                    reasoning=reasoning
                )
                
            except Exception as e:
                logger.error(f"Analysis error for {market.id}: {e}")
                return None
    
    def _build_prompt(self, market: Market) -> str:
        """Build analysis prompt with research context."""
        parts = [
            f"MARKET QUESTION: {market.question}",
            f"\nCATEGORY: {market.category or 'Unknown'}",
            f"END DATE: {market.end_date or 'Unknown'}",
            f"\nCURRENT PRICES:",
            f"  YES: ${market.yes_price:.2f}" if market.yes_price else "  YES: Unknown",
            f"  NO: ${market.no_price:.2f}" if market.no_price else "  NO: Unknown",
            f"\nMARKET METRICS:",
            f"  Volume: ${market.volume:,.0f}",
            f"  Liquidity: ${market.liquidity:,.0f}",
        ]
        
        if market.description:
            parts.append(f"\nDESCRIPTION: {market.description[:500]}")
        
        if market.research_summary:
            parts.append(f"\nRESEARCH DATA:\n{market.research_summary}")
        else:
            parts.append("\nRESEARCH DATA: No research available - use general knowledge only.")
        
        parts.append("\nProvide your probability estimate, confidence, and reasoning as JSON.")
        
        return "\n".join(parts)
    
    async def _call_ollama(self, prompt: str) -> Optional[str]:
        """Call Ollama API."""
        try:
            url = f"{self.ollama_url}/api/generate"
            payload = {
                "model": self.model,
                "prompt": prompt,
                "system": self.SYSTEM_PROMPT,
                "stream": False,
                "options": {
                    "temperature": 0.3,  # Lower for more consistent outputs
                    "num_predict": 500,
                }
            }
            
            async with self.session.post(url, json=payload) as resp:
                if resp.status != 200:
                    logger.error(f"Ollama error: {resp.status}")
                    return None
                
                data = await resp.json()
                return data.get("response", "")
                
        except Exception as e:
            logger.error(f"Ollama call failed: {e}")
            return None
    
    def _parse_response(self, response: str) -> Optional[dict]:
        """Parse LLM response to extract probability, confidence, reasoning."""
        try:
            # Try to find JSON in response
            # Look for JSON block
            json_match = re.search(r'\{[^{}]*"probability"[^{}]*\}', response, re.DOTALL)
            
            if json_match:
                data = json.loads(json_match.group())
            else:
                # Try parsing entire response as JSON
                data = json.loads(response.strip())
            
            # Validate fields
            prob = float(data.get("probability", 0.5))
            conf = float(data.get("confidence", 0.5))
            reasoning = str(data.get("reasoning", "No reasoning provided"))
            
            # Clamp values
            prob = max(0.0, min(1.0, prob))
            conf = max(0.0, min(1.0, conf))
            
            return {
                "probability": prob,
                "confidence": conf,
                "reasoning": reasoning[:500],  # Limit length
            }
            
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(f"Failed to parse response: {e}")
            logger.debug(f"Response was: {response[:200]}")
            return None
    
    def _determine_signal(self, edge: float, confidence: float, market: Market) -> str:
        """Determine trading signal based on edge and confidence."""
        # BUY if edge > 5% and confidence > 60%
        if edge > 0.05 and confidence > 0.6:
            return "BUY"
        
        # AVOID if negative edge with high confidence
        if edge < -0.10 and confidence > 0.7:
            return "AVOID"
        
        # Everything else is SKIP
        return "SKIP"
    
    def _calculate_size(self, liquidity: float, edge: float, confidence: float) -> float:
        """Calculate recommended bet size based on liquidity."""
        # Base max size on liquidity
        if liquidity < 500:
            max_size = 10
        elif liquidity < 2000:
            max_size = 25
        elif liquidity < 10000:
            max_size = 50
        else:
            max_size = 100
        
        # Scale by edge and confidence (simple Kelly-inspired)
        # Full size only for very high edge + confidence
        scale = min(1.0, (edge * 10) * confidence)
        scale = max(0.1, scale)  # Minimum 10% of max
        
        return round(max_size * scale, 2)


async def analyze_markets(markets: List[Market], db: Database,
                         ollama_url: str = "http://100.112.76.34:11434",
                         model: str = "qwen2.5:32b",
                         max_concurrent: int = 10) -> List[Signal]:
    """Convenience function to analyze markets."""
    async with Analyzer(ollama_url, model, max_concurrent) as analyzer:
        return await analyzer.analyze_markets(markets, db)
