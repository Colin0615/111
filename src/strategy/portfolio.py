"""Correlation-aware portfolio construction and position optimization.

Prevents concentration risk by tracking market correlations and
optimizing position sizes across the entire portfolio.

Key rules:
- Max 10% of bankroll per market
- Max 30% in a correlation cluster
- Diversify across uncorrelated categories
"""

from __future__ import annotations

import math
import structlog
from dataclasses import dataclass

from src.core.config import config

log = structlog.get_logger()

# Estimated correlations between market categories
# Based on domain knowledge; refined with actual data over time
CATEGORY_CORRELATIONS = {
    ("crypto", "crypto"): 0.7,       # BTC/ETH prices correlated
    ("politics", "politics"): 0.5,    # Same-party elections
    ("economics", "economics"): 0.4,
    ("tech", "tech"): 0.3,
    ("sports", "sports"): 0.1,        # Mostly independent
    # Cross-category (low by default)
    ("crypto", "politics"): 0.15,
    ("crypto", "economics"): 0.3,
    ("politics", "economics"): 0.25,
}


def get_correlation(cat1: str, cat2: str) -> float:
    """Get estimated correlation between two market categories."""
    if cat1 == cat2:
        return CATEGORY_CORRELATIONS.get((cat1, cat2), 0.3)
    key1 = (cat1, cat2)
    key2 = (cat2, cat1)
    return CATEGORY_CORRELATIONS.get(key1, CATEGORY_CORRELATIONS.get(key2, 0.1))


@dataclass
class AllocationResult:
    market_id: str
    category: str
    side: str
    raw_kelly_size: float
    adjusted_size: float
    reason: str


def optimize_allocations(
    signals: list[dict],
    current_positions: list[dict],
    cash_available: float,
) -> list[AllocationResult]:
    """Optimize position sizes across multiple signals.

    Considers:
    - Individual Kelly sizing
    - Category concentration limits
    - Correlation between positions
    - Available cash
    """
    tc = config.trading
    bankroll = tc.initial_bankroll
    max_per_market = tc.max_position_size
    max_per_category = bankroll * 0.30
    max_total_exposure = bankroll * 0.80

    # Current exposure by category
    category_exposure: dict[str, float] = {}
    total_invested = 0.0
    for pos in current_positions:
        cat = pos.get("category", "other")
        invested = pos.get("shares", 0) * pos.get("avg_price", 0)
        category_exposure[cat] = category_exposure.get(cat, 0) + invested
        total_invested += invested

    allocations: list[AllocationResult] = []

    for sig in signals:
        market_id = sig.get("condition_id", "")
        category = sig.get("category", "other")
        edge = sig.get("edge", 0)
        price = sig.get("market_price", 0.5)
        confidence = sig.get("confidence", 5) / 10.0
        side = sig.get("side", "BUY_YES")

        # Kelly sizing
        if edge <= 0 or price <= 0 or price >= 1:
            continue
        kelly = edge / (1 - price)
        raw_size = kelly * tc.kelly_fraction * bankroll
        raw_size = max(raw_size, 2.0)  # minimum $2

        # Apply constraints
        adjusted = raw_size
        reason = "kelly"

        # Cap per market
        if adjusted > max_per_market:
            adjusted = max_per_market
            reason = f"capped at ${max_per_market:.0f}/market"

        # Category concentration
        cat_used = category_exposure.get(category, 0)
        if cat_used + adjusted > max_per_category:
            adjusted = max(max_per_category - cat_used, 0)
            reason = f"category limit (${cat_used:.0f} already in {category})"

        # Total exposure
        if total_invested + adjusted > max_total_exposure:
            adjusted = max(max_total_exposure - total_invested, 0)
            reason = "total exposure limit"

        # Cash constraint
        if adjusted > cash_available:
            adjusted = max(cash_available - 1, 0)  # leave $1 buffer
            reason = "cash constraint"

        # Correlation discount: reduce size if correlated with existing positions
        corr_discount = 1.0
        for pos in current_positions:
            pos_cat = pos.get("category", "other")
            corr = get_correlation(category, pos_cat)
            if corr > 0.3:
                # Reduce by correlation * existing position weight
                pos_weight = (pos.get("shares", 0) * pos.get("avg_price", 0)) / max(bankroll, 1)
                corr_discount -= corr * pos_weight * 0.5
        corr_discount = max(corr_discount, 0.3)  # floor at 30%
        if corr_discount < 1.0:
            adjusted *= corr_discount
            reason += f" (corr discount {corr_discount:.0%})"

        # Confidence adjustment
        adjusted *= min(confidence, 1.0)

        adjusted = round(adjusted, 2)

        if adjusted >= 2.0:  # minimum viable trade
            allocations.append(AllocationResult(
                market_id=market_id,
                category=category,
                side=side,
                raw_kelly_size=round(raw_size, 2),
                adjusted_size=adjusted,
                reason=reason,
            ))
            # Update tracking
            category_exposure[category] = category_exposure.get(category, 0) + adjusted
            total_invested += adjusted
            cash_available -= adjusted

    log.info("portfolio_optimized",
             n_signals=len(signals),
             n_allocated=len(allocations),
             total_allocated=sum(a.adjusted_size for a in allocations))

    return allocations
