"""Polymarket API client for fetching markets."""
import asyncio
import aiohttp
from typing import List, Optional, Tuple
from datetime import datetime
import logging

from .models import Market
from .database import Database

logger = logging.getLogger(__name__)


class MarketFetcher:
    """Fetches markets from Polymarket API."""
    
    # Polymarket CLOB API endpoints
    BASE_URL = "https://clob.polymarket.com"
    GAMMA_URL = "https://gamma-api.polymarket.com"
    
    def __init__(self, db: Database):
        self.db = db
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=60)
        )
        return self
    
    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()
    
    async def fetch_all_markets(self, limit: Optional[int] = None) -> Tuple[List[Market], List[str]]:
        """
        Fetch all markets from Polymarket.
        Returns (all_markets, new_market_ids).
        """
        markets = []
        new_ids = []
        
        # Fetch from Gamma API (has more market data)
        try:
            gamma_markets = await self._fetch_gamma_markets(limit)
            markets.extend(gamma_markets)
            logger.info(f"Fetched {len(gamma_markets)} markets from Gamma API")
        except Exception as e:
            logger.error(f"Error fetching from Gamma API: {e}")
        
        # Upsert to database and track new markets
        if markets:
            new_ids = self.db.upsert_markets(markets)
            logger.info(f"Upserted {len(markets)} markets, {len(new_ids)} are new")
        
        return markets, new_ids
    
    async def _fetch_gamma_markets(self, limit: Optional[int] = None) -> List[Market]:
        """Fetch markets from Gamma API with pagination."""
        markets = []
        offset = 0
        page_size = 100
        
        while True:
            url = f"{self.GAMMA_URL}/markets"
            params = {
                "limit": page_size,
                "offset": offset,
                "active": "true", "closed": "false",
            }
            
            try:
                async with self.session.get(url, params=params) as resp:
                    if resp.status != 200:
                        logger.error(f"Gamma API error: {resp.status}")
                        break
                    
                    data = await resp.json()
                    
                    if not data:
                        break
                    
                    for item in data:
                        market = self._parse_gamma_market(item)
                        if market:
                            markets.append(market)
                    
                    # Check if we've hit the limit
                    if limit and len(markets) >= limit:
                        markets = markets[:limit]
                        break
                    
                    # Check if there are more pages
                    if len(data) < page_size:
                        break
                    
                    offset += page_size
                    
            except Exception as e:
                logger.error(f"Error fetching page at offset {offset}: {e}")
                break
        
        return markets
    
    def _parse_gamma_market(self, data: dict) -> Optional[Market]:
        """Parse a market from Gamma API response."""
        try:
            market_id = data.get("id") or data.get("condition_id")
            if not market_id:
                return None
            
            question = data.get("question", "")
            if not question:
                return None
            
            # Determine status
            status = "active"
            if data.get("closed"):
                status = "closed"
            if data.get("resolved"):
                status = "resolved"
            
            # Parse prices - Gamma uses outcomePrices
            yes_price = None
            no_price = None
            
            outcome_prices = data.get("outcomePrices")
            if outcome_prices:
                if isinstance(outcome_prices, str):
                    # Sometimes it's a JSON string
                    import json
                    try:
                        outcome_prices = json.loads(outcome_prices)
                    except:
                        pass
                
                if isinstance(outcome_prices, list) and len(outcome_prices) >= 2:
                    try:
                        yes_price = float(outcome_prices[0])
                        no_price = float(outcome_prices[1])
                    except (ValueError, TypeError):
                        pass
            
            # If no prices, try clobTokenIds approach (would need additional API call)
            if yes_price is None:
                yes_price = data.get("bestBid", 0.5)
                no_price = 1 - yes_price if yes_price else 0.5
            
            return Market(
                id=market_id,
                question=question,
                description=data.get("description", ""),
                category=data.get("category") or data.get("groupSlug", ""),
                end_date=data.get("endDate") or data.get("end_date_iso"),
                yes_price=yes_price,
                no_price=no_price,
                volume=float(data.get("volume", 0) or 0),
                liquidity=float(data.get("liquidity", 0) or 0),
                status=status,
            )
        except Exception as e:
            logger.warning(f"Failed to parse market: {e}")
            return None
    
    async def update_prices(self, market_ids: Optional[List[str]] = None) -> int:
        """
        Update prices for existing markets.
        Returns count of updated markets.
        """
        if market_ids is None:
            # Get all active market IDs from database
            active_markets = self.db.get_markets(status="active")
            market_ids = [m.id for m in active_markets]
        
        updated = 0
        
        # Batch fetch and update
        # For now, refetch all markets and let upsert handle updates
        markets, _ = await self.fetch_all_markets()
        updated = len(markets)
        
        return updated
    
    async def check_resolved(self) -> List[str]:
        """
        Check for newly resolved markets.
        Returns list of market IDs that were marked as resolved.
        """
        resolved_ids = []
        
        # Get active markets from DB
        active_markets = self.db.get_markets(status="active")
        
        # Fetch current state from API
        current_markets, _ = await self.fetch_all_markets()
        current_by_id = {m.id: m for m in current_markets}
        
        # Check which ones are now resolved
        for market in active_markets:
            current = current_by_id.get(market.id)
            if current and current.status == "resolved":
                self.db.mark_resolved(market.id)
                resolved_ids.append(market.id)
            elif not current:
                # Market no longer in API - likely resolved or removed
                self.db.mark_resolved(market.id)
                resolved_ids.append(market.id)
        
        return resolved_ids


async def fetch_markets(db: Database, limit: Optional[int] = None) -> Tuple[List[Market], List[str]]:
    """Convenience function to fetch markets."""
    async with MarketFetcher(db) as fetcher:
        return await fetcher.fetch_all_markets(limit)
