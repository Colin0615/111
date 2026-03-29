"""Polymarket market data client.

Uses the Gamma API (public, no auth) for market discovery and metadata,
and the CLOB API for orderbook/price data. Trading uses the CLOB client.
"""

from __future__ import annotations

import httpx
import structlog
from datetime import datetime, timezone
from typing import Optional

from src.core.config import config

log = structlog.get_logger()

GAMMA_URL = config.polymarket.gamma_url
CLOB_URL = config.polymarket.clob_url


async def fetch_active_markets(
    limit: int = 100,
    category: Optional[str] = None,
    min_volume: float = 0,
) -> list[dict]:
    """Fetch active markets from Gamma API with optional filters."""
    params = {
        "limit": limit,
        "active": "true",
        "closed": "false",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{GAMMA_URL}/markets", params=params)
        resp.raise_for_status()
        markets = resp.json()

    results = []
    for m in markets:
        # Extract token prices from outcomes
        yes_price = 0.0
        no_price = 0.0
        tokens = m.get("tokens", [])
        for token in tokens:
            outcome = token.get("outcome", "").upper()
            price = float(token.get("price", 0))
            if outcome == "YES":
                yes_price = price
            elif outcome == "NO":
                no_price = price

        volume = float(m.get("volume", 0) or 0)
        liquidity = float(m.get("liquidity", 0) or 0)

        # Apply filters
        if min_volume > 0 and volume < min_volume:
            continue
        if category and m.get("category", "").lower() != category.lower():
            continue

        results.append({
            "condition_id": m.get("conditionId", m.get("condition_id", "")),
            "question": m.get("question", ""),
            "description": m.get("description", ""),
            "category": m.get("category", ""),
            "end_date": m.get("endDate", m.get("end_date_iso", "")),
            "yes_price": yes_price,
            "no_price": no_price,
            "volume_24h": volume,
            "liquidity": liquidity,
            "market_slug": m.get("slug", ""),
            "tokens": tokens,
        })

    results.sort(key=lambda x: x["volume_24h"], reverse=True)
    log.info("fetched_markets", count=len(results), total_raw=len(markets))
    return results


async def fetch_market_detail(condition_id: str) -> Optional[dict]:
    """Fetch detailed info for a single market."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{GAMMA_URL}/markets", params={"id": condition_id})
        resp.raise_for_status()
        markets = resp.json()

    if not markets:
        return None
    return markets[0]


async def fetch_orderbook(token_id: str) -> dict:
    """Fetch the order book for a specific token from CLOB API."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{CLOB_URL}/book", params={"token_id": token_id})
        resp.raise_for_status()
        return resp.json()


async def fetch_price(token_id: str) -> dict:
    """Fetch current price from CLOB API."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{CLOB_URL}/price", params={"token_id": token_id})
        resp.raise_for_status()
        return resp.json()


async def fetch_midpoint(token_id: str) -> Optional[float]:
    """Fetch midpoint price for a token."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{CLOB_URL}/midpoint", params={"token_id": token_id})
        resp.raise_for_status()
        data = resp.json()
    mid = data.get("mid")
    return float(mid) if mid is not None else None


def categorize_market(question: str, description: str = "") -> str:
    """Simple keyword-based market categorization using word boundaries."""
    import re
    text = (question + " " + description).lower()

    categories = [
        ("crypto", ["bitcoin", "btc", "ethereum", "eth", "crypto", "solana", "blockchain", "defi"]),
        ("politics", ["president", "election", "congress", "senate", "vote", "trump", "biden", "governor", "democrat", "republican"]),
        ("economics", ["gdp", "inflation", "cpi", "interest rate", "unemployment", "recession", "federal reserve"]),
        ("tech", ["apple", "google", "artificial intelligence", "tesla", "spacex", "launch", "iphone"]),
        ("sports", ["nba", "nfl", "mlb", "soccer", "football", "championship", "playoff", "world cup"]),
    ]

    for cat_name, keywords in categories:
        for kw in keywords:
            # Use word boundary matching for short keywords to avoid false positives
            if len(kw) <= 3:
                if re.search(rf"\b{re.escape(kw)}\b", text):
                    return cat_name
            else:
                if kw in text:
                    return cat_name
    return "other"
