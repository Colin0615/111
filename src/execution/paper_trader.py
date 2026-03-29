"""Paper trading execution layer.

Records trades in the database without sending real orders.
When ready for live trading, swap this for the real executor.
"""

from __future__ import annotations

import structlog
from datetime import datetime, timezone

from src.core import database as db
from src.strategy.signals import Signal

log = structlog.get_logger()


async def execute_paper_trade(signal: Signal) -> dict:
    """Execute a paper trade: record it in the DB and update portfolio."""
    now = datetime.now(timezone.utc).isoformat()
    shares = signal.suggested_size_usd / signal.market_price if signal.market_price > 0 else 0

    trade = {
        "condition_id": signal.condition_id,
        "timestamp": now,
        "side": signal.side,
        "price": signal.market_price,
        "size_usd": signal.suggested_size_usd,
        "shares": round(shares, 4),
        "ai_probability": signal.ai_probability,
        "edge": signal.edge,
        "status": "PAPER",
        "order_id": None,
        "notes": f"Paper trade | Edge: {signal.edge:.1%} | Confidence: {signal.confidence}",
    }

    trade_id = await db.save_trade(trade)
    trade["id"] = trade_id

    # Save position
    conn = await db.get_db()
    token_side = "YES" if "YES" in signal.side else "NO"
    await conn.execute(
        """INSERT INTO positions (condition_id, side, shares, avg_price, current_price, unrealized_pnl)
           VALUES (?, ?, ?, ?, ?, 0)
           ON CONFLICT(condition_id) DO UPDATE SET
             shares = shares + ?,
             avg_price = (avg_price * shares + ? * ?) / (shares + ?),
             current_price = ?""",
        (
            signal.condition_id, token_side, shares, signal.market_price, signal.market_price,
            shares, signal.market_price, shares, shares, signal.market_price,
        ),
    )
    await conn.commit()
    await conn.close()

    log.info(
        "paper_trade_executed",
        trade_id=trade_id,
        side=signal.side,
        question=signal.question[:50],
        price=f"${signal.market_price:.3f}",
        size=f"${signal.suggested_size_usd:.2f}",
        shares=f"{shares:.2f}",
    )

    return trade


async def update_positions_pnl() -> list[dict]:
    """Update unrealized P&L for all open positions using current market prices."""
    positions = await db.get_open_positions()
    conn = await db.get_db()

    updated = []
    for pos in positions:
        current_price = pos.get("yes_price", 0) if pos["side"] == "YES" else pos.get("no_price", 0)
        if current_price and current_price > 0:
            unrealized = (current_price - pos["avg_price"]) * pos["shares"]
            await conn.execute(
                "UPDATE positions SET current_price = ?, unrealized_pnl = ? WHERE condition_id = ?",
                (current_price, round(unrealized, 4), pos["condition_id"]),
            )
            pos["current_price"] = current_price
            pos["unrealized_pnl"] = unrealized
        updated.append(pos)

    # Update total P&L in portfolio
    total_unrealized = sum(p.get("unrealized_pnl", 0) for p in updated)
    await conn.execute(
        "UPDATE portfolio SET total_pnl = ?, updated_at = ? WHERE id = 1",
        (round(total_unrealized, 4), datetime.now(timezone.utc).isoformat()),
    )
    await conn.commit()
    await conn.close()

    return updated
