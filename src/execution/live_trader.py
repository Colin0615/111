"""Live trading execution using py-clob-client.

WARNING: This sends REAL orders with REAL money.
Only use after thorough paper trading validation.
"""

from __future__ import annotations

import structlog
from datetime import datetime, timezone
from typing import Optional

from src.core.config import config
from src.core import database as db
from src.strategy.signals import Signal

log = structlog.get_logger()

_clob_client = None


def _get_clob_client():
    """Lazy-init the CLOB client. Only created when actually trading."""
    global _clob_client
    if _clob_client is not None:
        return _clob_client

    pk = config.polymarket.private_key
    if not pk:
        raise RuntimeError(
            "POLYMARKET_PRIVATE_KEY not set. "
            "Live trading requires a funded Polygon wallet."
        )

    try:
        from py_clob_client.client import ClobClient
        client = ClobClient(
            config.polymarket.clob_url,
            key=pk,
            chain_id=config.polymarket.chain_id,
            signature_type=0,  # EOA wallet
        )
        # Derive or load API credentials
        api_key = config.polymarket.api_key
        if api_key:
            from py_clob_client.clob_types import ApiCreds
            client.set_api_creds(ApiCreds(
                api_key=api_key,
                api_secret=config.polymarket.api_secret,
                api_passphrase=config.polymarket.api_passphrase,
            ))
        else:
            client.set_api_creds(client.create_or_derive_api_creds())
            log.info("derived_api_creds", msg="Auto-derived CLOB API credentials")

        _clob_client = client
        log.info("clob_client_initialized")
        return client

    except ImportError:
        raise RuntimeError("py-clob-client not installed. Run: pip install py-clob-client")


def _find_token_id(market: dict, side: str) -> Optional[str]:
    """Find the token ID for YES or NO from market data."""
    token_side = "Yes" if "YES" in side else "No"
    for token in market.get("tokens", []):
        if token.get("outcome", "").lower() == token_side.lower():
            return token.get("token_id")
    return None


async def execute_live_trade(signal: Signal, market: dict) -> dict:
    """Place a real limit order on Polymarket.

    Uses GTC (Good-Til-Cancelled) limit orders for maker rebates.
    """
    client = _get_clob_client()
    now = datetime.now(timezone.utc).isoformat()

    token_id = _find_token_id(market, signal.side)
    if not token_id:
        raise ValueError(f"Could not find token_id for {signal.side} in market {signal.condition_id}")

    shares = signal.suggested_size_usd / signal.market_price if signal.market_price > 0 else 0

    # Place limit order slightly better than market for maker rebate
    # For BUY: bid slightly below current ask
    limit_price = round(signal.market_price, 3)

    try:
        from py_clob_client.order_builder.constants import BUY
        order_args = {
            "token_id": token_id,
            "price": limit_price,
            "size": round(shares, 2),
            "side": BUY,
        }

        log.info("placing_live_order", **order_args)

        signed_order = client.create_order(order_args)
        response = client.post_order(signed_order)

        order_id = response.get("orderID", response.get("id", "unknown"))

        trade = {
            "condition_id": signal.condition_id,
            "timestamp": now,
            "side": signal.side,
            "price": limit_price,
            "size_usd": signal.suggested_size_usd,
            "shares": round(shares, 4),
            "ai_probability": signal.ai_probability,
            "edge": signal.edge,
            "status": "PENDING",
            "order_id": order_id,
            "notes": f"LIVE order | Edge: {signal.edge:.1%}",
        }
        trade_id = await db.save_trade(trade)
        trade["id"] = trade_id

        log.info("live_order_placed", order_id=order_id, trade_id=trade_id)
        return trade

    except Exception as e:
        log.error("live_order_failed", error=str(e), signal=signal.condition_id)
        trade = {
            "condition_id": signal.condition_id,
            "timestamp": now,
            "side": signal.side,
            "price": limit_price,
            "size_usd": signal.suggested_size_usd,
            "shares": round(shares, 4),
            "ai_probability": signal.ai_probability,
            "edge": signal.edge,
            "status": "FAILED",
            "order_id": None,
            "notes": f"FAILED: {str(e)[:200]}",
        }
        await db.save_trade(trade)
        raise
