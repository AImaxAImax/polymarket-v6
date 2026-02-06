"""
Alpha Scanner — V6 Core Component

Scans all active Polymarket markets, gets AI probability estimates,
and flags opportunities with 20%+ edge.

Key fix: Bayesian anchoring + sanity checks to prevent LLM hallucination.
Added: retry/backoff for all external HTTP calls.
"""

import asyncio
import json
import logging
import re
import time
from typing import Optional

import httpx

from .config import V6Config, config
from .models import AlphaOpportunity, Direction, Market, ScanResult

logger = logging.getLogger(__name__)


class AlphaScanner:
    """Scans markets for alpha opportunities using AI estimates."""

    def __init__(self, cfg: V6Config = config):
        self.cfg = cfg
        self._http: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._http = httpx.AsyncClient(timeout=60)
        return self

    async def __aexit__(self, *args):
        if self._http:
            await self._http.aclose()

    # === HTTP with retry/backoff ===

    async def _request_with_retry(
        self, method: str, url: str, **kwargs
    ) -> httpx.Response:
        """Make HTTP request with exponential backoff retry."""
        max_retries = self.cfg.http_max_retries
        backoff = self.cfg.http_retry_backoff

        for attempt in range(max_retries + 1):
            try:
                resp = await getattr(self._http, method)(url, **kwargs)
                resp.raise_for_status()
                return resp
            except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
                if attempt == max_retries:
                    raise
                wait = backoff * (2 ** attempt)
                logger.debug(
                    f"Retry {attempt + 1}/{max_retries} for {url} "
                    f"after {wait:.1f}s: {e}"
                )
                await asyncio.sleep(wait)

    # === Polymarket API ===

    async def fetch_all_markets(self) -> list[Market]:
        """Fetch all active, non-closed markets from Polymarket."""
        markets = []
        offset = 0
        limit = 100

        logger.info("Fetching active markets from Polymarket...")

        while True:
            url = f"{self.cfg.polymarket_api}/markets"
            params = {
                "active": "true",
                "closed": "false",
                "limit": limit,
                "offset": offset,
            }

            try:
                resp = await self._request_with_retry("get", url, params=params)
                data = resp.json()

                if not data:
                    break

                for m in data:
                    market = self._parse_market(m)
                    if market:
                        markets.append(market)

                if len(data) < limit:
                    break

                offset += limit

            except Exception as e:
                logger.error(f"Error fetching markets at offset {offset}: {e}")
                break

        logger.info(f"Fetched {len(markets)} active markets")
        return markets

    def _parse_market(self, raw: dict) -> Optional[Market]:
        """Parse raw API response into Market model."""
        try:
            prices_str = raw.get("outcomePrices", "[0.5, 0.5]")
            prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
            prices = [float(p) for p in prices]

            outcomes_str = raw.get("outcomes", '["Yes", "No"]')
            outcomes = json.loads(outcomes_str) if isinstance(outcomes_str, str) else outcomes_str

            category = None
            events = raw.get("events", [])
            if events:
                series = events[0].get("series", [])
                if series:
                    category = series[0].get("title")
                elif events[0].get("title"):
                    category = events[0].get("title")

            return Market(
                id=raw["id"],
                question=raw["question"],
                slug=raw.get("slug", ""),
                description=raw.get("description", ""),
                outcome_prices=prices,
                outcomes=outcomes,
                active=raw.get("active", True),
                closed=raw.get("closed", False),
                volume_24h=float(raw.get("volume24hr", 0) or 0),
                liquidity=float(raw.get("liquidityNum", 0) or 0),
                category=category,
            )
        except Exception as e:
            logger.debug(f"Failed to parse market {raw.get('id')}: {e}")
            return None

    # === Ollama AI Estimates (with Bayesian anchoring) ===

    async def get_ai_estimate(self, question: str, market_price: float) -> dict:
        """
        Get AI probability estimate WITH Bayesian anchoring.

        Key improvements:
        1. Tell the LLM what the market price is (anchoring)
        2. Ask for confidence level and reasoning
        3. Apply sanity checks to prevent hallucination-based alpha
        """
        market_pct = market_price * 100

        prompt = f"""You are a probability calibration expert. Estimate the TRUE probability of this event.

MARKET: {question}
CURRENT MARKET PRICE: {market_pct:.1f}%

The market price reflects traders with real money at stake.
ONLY disagree if you have strong reasoning.

Respond in this EXACT format:
ESTIMATE: [number 0-100]
CONFIDENCE: [LOW/MEDIUM/HIGH]
REASONING: [1-2 sentences, especially if you disagree with market]"""

        try:
            resp = await self._request_with_retry(
                "post",
                f"{self.cfg.ollama_url}/api/generate",
                json={
                    "model": self.cfg.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=self.cfg.ollama_timeout,
            )

            result = resp.json()
            response_text = result.get("response", "").strip()
            return self._parse_ai_response(response_text, market_price)

        except httpx.TimeoutException:
            logger.debug(f"Timeout getting AI estimate for: {question[:50]}...")
            return {
                "estimate": market_price,
                "confidence": "LOW",
                "reasoning": "Timeout",
                "filtered": True,
            }
        except Exception as e:
            logger.debug(f"Error getting AI estimate: {e}")
            return {
                "estimate": market_price,
                "confidence": "LOW",
                "reasoning": str(e),
                "filtered": True,
            }

    def _parse_ai_response(self, response: str, market_price: float) -> dict:
        """Parse and validate AI response with sanity checks."""
        result = {
            "estimate": market_price,
            "raw_estimate": None,
            "confidence": "LOW",
            "reasoning": "",
            "filtered": False,
        }

        # Extract estimate
        estimate_match = re.search(
            r"ESTIMATE:\s*(\d+(?:\.\d+)?)", response, re.IGNORECASE
        )
        if estimate_match:
            raw = float(estimate_match.group(1)) / 100.0
            raw = max(0, min(1, raw))
            result["raw_estimate"] = raw
            result["estimate"] = raw

        # Extract confidence
        conf_match = re.search(
            r"CONFIDENCE:\s*(LOW|MEDIUM|HIGH)", response, re.IGNORECASE
        )
        if conf_match:
            result["confidence"] = conf_match.group(1).upper()

        # Extract reasoning
        reason_match = re.search(
            r"REASONING:\s*(.+?)(?:\n|$)", response, re.IGNORECASE | re.DOTALL
        )
        if reason_match:
            result["reasoning"] = reason_match.group(1).strip()[:200]

        return self._apply_sanity_checks(result, market_price)

    def _apply_sanity_checks(self, result: dict, market_price: float) -> dict:
        """Apply calibration to prevent hallucination-based alpha."""
        if result["raw_estimate"] is None:
            result["filtered"] = True
            return result

        raw = result["raw_estimate"]
        edge = abs(raw - market_price)

        # CHECK 1: Cap maximum edge
        max_edge = self.cfg.alpha_max_edge
        if edge > max_edge:
            if raw > market_price:
                result["estimate"] = market_price + max_edge
            else:
                result["estimate"] = market_price - max_edge
            result["capped"] = True
            result["original_edge"] = edge
            logger.debug(f"Edge capped from {edge:.1%} to {max_edge:.1%}")

        # CHECK 2: Extreme markets (<5% or >95%) need higher edge + confidence
        extreme_threshold = self.cfg.alpha_extreme_threshold
        extreme_min_edge = self.cfg.alpha_extreme_min_edge

        is_extreme = market_price < extreme_threshold or market_price > (
            1 - extreme_threshold
        )
        if is_extreme:
            recalc_edge = abs(result["estimate"] - market_price)
            if recalc_edge < extreme_min_edge:
                result["estimate"] = market_price
                result["filtered"] = True
                result["filter_reason"] = (
                    f"Extreme market ({market_price:.1%}), "
                    f"edge {recalc_edge:.1%} < {extreme_min_edge:.1%}"
                )
            elif result["confidence"] == "LOW":
                result["estimate"] = market_price
                result["filtered"] = True
                result["filter_reason"] = "Low confidence on extreme market"

        # CHECK 3: Require reasoning for large disagreement (>10% edge)
        if self.cfg.alpha_require_reasoning:
            recalc_edge = abs(result["estimate"] - market_price)
            if recalc_edge > 0.10 and not result.get("reasoning"):
                result["estimate"] = market_price
                result["filtered"] = True
                result["filter_reason"] = "Large edge without reasoning"

        return result

    # === Main Scan Logic ===

    async def scan(self, max_markets: Optional[int] = None) -> ScanResult:
        """Scan all markets and find alpha opportunities."""
        start_time = time.time()
        errors = []
        opportunities = []
        filtered_count = 0

        markets = await self.fetch_all_markets()

        if max_markets:
            markets = markets[:max_markets]

        total = len(markets)
        logger.info(
            f"Scanning {total} markets for alpha "
            f"(threshold: {self.cfg.alpha_threshold:.0%})..."
        )

        for i, market in enumerate(markets):
            if (i + 1) % self.cfg.log_interval == 0:
                logger.info(
                    f"Progress: {i + 1}/{total} scanned, "
                    f"{len(opportunities)} found, {filtered_count} filtered"
                )

            if market.liquidity < self.cfg.min_liquidity:
                continue

            market_price = market.yes_price

            # Get AI estimate WITH market price context (the fix)
            ai_result = await self.get_ai_estimate(market.question, market_price)

            if ai_result.get("filtered"):
                filtered_count += 1
                continue

            ai_estimate = ai_result["estimate"]
            edge = abs(ai_estimate - market_price)

            if edge < self.cfg.alpha_min_edge:
                continue

            if edge >= self.cfg.alpha_threshold:
                direction = Direction.YES if ai_estimate > market_price else Direction.NO

                opp = AlphaOpportunity(
                    market_id=market.id,
                    question=market.question,
                    category=market.category,
                    slug=market.slug,
                    market_price=market_price,
                    ai_estimate=ai_estimate,
                    edge_pct=edge * 100,
                    direction=direction,
                    volume_24h=market.volume_24h,
                    liquidity=market.liquidity,
                    reasoning=ai_result.get("reasoning"),
                )
                opportunities.append(opp)

                conf = ai_result.get("confidence", "?")
                reason = ai_result.get("reasoning", "")[:60]
                logger.info(f"ALPHA: {opp} [conf: {conf}] {reason}")

            await asyncio.sleep(self.cfg.ollama_delay)

        opportunities.sort(key=lambda x: x.edge_pct, reverse=True)

        duration = time.time() - start_time
        alpha_rate = len(opportunities) / total * 100 if total > 0 else 0
        logger.info(
            f"Scan complete in {duration:.1f}s — "
            f"{len(opportunities)} opportunities ({alpha_rate:.1f}% alpha rate), "
            f"{filtered_count} filtered"
        )

        return ScanResult(
            total_markets_scanned=total,
            markets_with_alpha=len(opportunities),
            opportunities=opportunities,
            scan_duration_sec=duration,
            errors=errors,
        )


async def run_scan(max_markets: Optional[int] = None) -> ScanResult:
    """Convenience function to run a scan."""
    async with AlphaScanner() as scanner:
        return await scanner.scan(max_markets=max_markets)


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    max_markets = int(sys.argv[1]) if len(sys.argv) > 1 else None
    result = asyncio.run(run_scan(max_markets))

    print("\n" + "=" * 60)
    print("ALPHA OPPORTUNITIES")
    print("=" * 60)

    for opp in result.opportunities[:20]:
        print(
            f"\n{opp.direction.value} @ {opp.market_price:.1%} -> "
            f"AI: {opp.ai_estimate:.1%} ({opp.edge_pct:.1f}% edge)"
        )
        print(f"  {opp.question}")
        print(f"  Liquidity: ${opp.liquidity:,.0f} | 24h Vol: ${opp.volume_24h:,.0f}")
        print(f"  https://polymarket.com/event/{opp.slug}")
