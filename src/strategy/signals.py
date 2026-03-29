"""Trading signal generation and risk management.

Core logic:
  edge = ai_probability - market_price
  Only trade when edge > threshold AND risk checks pass.
  Position size via fractional Kelly criterion.
"""

from __future__ import annotations

import structlog
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

from src.core.config import config
from src.core import database as db

log = structlog.get_logger()


@dataclass
class Signal:
    condition_id: str
    question: str
    side: str  # BUY_YES or BUY_NO
    edge: float  # ai_prob - market_price (can be negative for BUY_NO)
    ai_probability: float
    market_price: float
    confidence: float
    strength: str  # HIGH, MEDIUM, LOW
    suggested_size_usd: float
    reasoning: str


def generate_signal(analysis: dict, market: dict) -> Optional[Signal]:
    """Generate a trading signal from an AI analysis result.

    Returns None if the opportunity doesn't meet thresholds.
    """
    ai_prob = analysis["ai_probability"]
    yes_price = market.get("yes_price", 0.5)
    no_price = market.get("no_price", 0.5)
    confidence = analysis.get("confidence", 5)
    question = market.get("question", "")

    # Calculate edge for both sides
    yes_edge = ai_prob - yes_price  # Positive = YES is underpriced
    no_edge = (1 - ai_prob) - no_price  # Positive = NO is underpriced

    # Pick the better side
    if yes_edge > no_edge and yes_edge > 0:
        side = "BUY_YES"
        edge = yes_edge
        entry_price = yes_price
    elif no_edge > 0:
        side = "BUY_NO"
        edge = no_edge
        entry_price = no_price
    else:
        return None  # No edge on either side

    # Check minimum edge threshold
    tc = config.trading
    if edge < tc.min_edge_threshold:
        log.debug("signal_below_threshold", question=question[:50], edge=f"{edge:.1%}")
        return None

    # Check confidence (skip low confidence)
    if confidence < 4:
        log.debug("signal_low_confidence", question=question[:50], confidence=confidence)
        return None

    # Calculate position size using fractional Kelly
    kelly_fraction = edge / (1 - entry_price) if entry_price < 1 else 0
    raw_size = kelly_fraction * tc.kelly_fraction * tc.initial_bankroll
    size_usd = min(raw_size, tc.max_position_size)
    size_usd = max(size_usd, 2.0)  # Minimum $2 per trade

    # Determine strength
    if edge >= 0.15 and confidence >= 7:
        strength = "HIGH"
    elif edge >= 0.10 or confidence >= 6:
        strength = "MEDIUM"
    else:
        strength = "LOW"

    signal = Signal(
        condition_id=market["condition_id"],
        question=question,
        side=side,
        edge=edge,
        ai_probability=ai_prob,
        market_price=entry_price,
        confidence=confidence,
        strength=strength,
        suggested_size_usd=round(size_usd, 2),
        reasoning=analysis.get("reasoning", ""),
    )

    log.info(
        "signal_generated",
        question=question[:50],
        side=side,
        edge=f"{edge:.1%}",
        size=f"${size_usd:.2f}",
        strength=strength,
    )
    return signal


async def check_risk(signal: Signal) -> tuple[bool, str]:
    """Run risk checks against the signal. Returns (approved, reason)."""
    tc = config.trading

    # 1. Check portfolio state
    portfolio = await db.get_portfolio()
    if not portfolio:
        return False, "Portfolio not initialized"

    cash = portfolio.get("cash", 0)
    total_pnl = portfolio.get("total_pnl", 0)
    trades_today = portfolio.get("trades_today", 0)
    last_trade_date = portfolio.get("last_trade_date", "")

    # Reset daily counter if new day
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if last_trade_date != today:
        trades_today = 0

    # 2. Stop loss check (20% total drawdown)
    if total_pnl < -(tc.initial_bankroll * tc.stop_loss_pct):
        return False, f"STOP LOSS: Total P&L ${total_pnl:.2f} exceeds {tc.stop_loss_pct:.0%} limit"

    # 3. Daily trade limit
    if trades_today >= tc.max_daily_trades:
        return False, f"Daily limit reached: {trades_today}/{tc.max_daily_trades} trades today"

    # 4. Cash available
    if cash < signal.suggested_size_usd:
        return False, f"Insufficient cash: ${cash:.2f} < ${signal.suggested_size_usd:.2f}"

    # 5. Position concentration check
    positions = await db.get_open_positions()
    market_exposure = sum(1 for p in positions if p["condition_id"] == signal.condition_id)
    if market_exposure > 0:
        return False, f"Already have position in this market"

    # 6. Total exposure check (don't use more than 80% of bankroll)
    total_invested = tc.initial_bankroll - cash
    if total_invested + signal.suggested_size_usd > tc.initial_bankroll * 0.80:
        return False, f"Total exposure would exceed 80% of bankroll"

    return True, "All risk checks passed"


def rank_signals(signals: list[Signal]) -> list[Signal]:
    """Rank signals by expected value (edge * confidence)."""
    def score(s: Signal) -> float:
        confidence_weight = s.confidence / 10.0
        return s.edge * confidence_weight

    return sorted(signals, key=score, reverse=True)
