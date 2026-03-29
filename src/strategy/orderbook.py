"""Order book depth analysis and microstructure signals.

Analyzes the Polymarket CLOB order book to extract:
- Depth imbalance (buy vs sell pressure)
- Weighted midprice (volume-adjusted fair value)
- Wall detection (large resting orders as support/resistance)
- Spread analysis (liquidity confidence indicator)
"""

from __future__ import annotations

import structlog
from dataclasses import dataclass

log = structlog.get_logger()


@dataclass
class OrderBookSignal:
    depth_imbalance: float  # -1 (sell pressure) to +1 (buy pressure)
    weighted_midprice: float
    spread_pct: float
    is_liquid: bool
    walls: list[dict]
    signal_direction: str  # "bullish", "bearish", "neutral"
    signal_strength: float  # 0-1


def analyze_orderbook(book: dict, levels: int = 10) -> OrderBookSignal:
    """Full order book analysis returning composite signal."""
    bids = book.get("bids", [])
    asks = book.get("asks", [])

    # Depth imbalance
    bid_depth = sum(float(b.get("size", 0)) for b in bids[:levels])
    ask_depth = sum(float(a.get("size", 0)) for a in asks[:levels])
    total_depth = bid_depth + ask_depth
    imbalance = (bid_depth - ask_depth) / total_depth if total_depth > 0 else 0

    # Weighted midprice
    best_bid = float(bids[0]["price"]) if bids else 0
    best_ask = float(asks[0]["price"]) if asks else 1
    bid_vol = float(bids[0]["size"]) if bids else 0
    ask_vol = float(asks[0]["size"]) if asks else 0
    vol_total = bid_vol + ask_vol
    if vol_total > 0:
        w_mid = (best_bid * ask_vol + best_ask * bid_vol) / vol_total
    else:
        w_mid = (best_bid + best_ask) / 2

    # Spread
    spread = best_ask - best_bid
    midprice = (best_bid + best_ask) / 2
    spread_pct = spread / midprice if midprice > 0 else 1.0
    is_liquid = spread_pct < 0.05 and total_depth > 100

    # Wall detection (orders >3x average size)
    all_sizes = [float(b.get("size", 0)) for b in bids[:levels]] + \
                [float(a.get("size", 0)) for a in asks[:levels]]
    avg_size = sum(all_sizes) / max(len(all_sizes), 1) if all_sizes else 0
    walls = []
    threshold = avg_size * 3

    for bid in bids[:levels]:
        size = float(bid.get("size", 0))
        if size > threshold and avg_size > 0:
            walls.append({
                "side": "bid",
                "price": float(bid["price"]),
                "size": size,
                "multiple": size / avg_size,
            })
    for ask in asks[:levels]:
        size = float(ask.get("size", 0))
        if size > threshold and avg_size > 0:
            walls.append({
                "side": "ask",
                "price": float(ask["price"]),
                "size": size,
                "multiple": size / avg_size,
            })

    # Composite signal
    if imbalance > 0.3:
        direction = "bullish"
        strength = min(abs(imbalance), 1.0)
    elif imbalance < -0.3:
        direction = "bearish"
        strength = min(abs(imbalance), 1.0)
    else:
        direction = "neutral"
        strength = 0.0

    return OrderBookSignal(
        depth_imbalance=round(imbalance, 3),
        weighted_midprice=round(w_mid, 4),
        spread_pct=round(spread_pct, 4),
        is_liquid=is_liquid,
        walls=walls,
        signal_direction=direction,
        signal_strength=round(strength, 3),
    )


def flow_imbalance_trend(snapshots: list[dict], lookback: int = 20) -> dict:
    """Track depth imbalance over multiple snapshots to detect persistent pressure.

    A persistent and growing imbalance is much stronger than a momentary one.
    """
    if len(snapshots) < 3:
        return {"trend": "insufficient_data", "signal": 0}

    imbalances = []
    for snap in snapshots[-lookback:]:
        sig = analyze_orderbook(snap)
        imbalances.append(sig.depth_imbalance)

    # Exponentially weighted mean (recent matters more)
    import math
    weights = [math.exp(i / len(imbalances)) for i in range(len(imbalances))]
    w_total = sum(weights)
    weighted_avg = sum(im * w for im, w in zip(imbalances, weights)) / w_total

    # Trend: simple linear regression slope
    n = len(imbalances)
    x_mean = (n - 1) / 2
    y_mean = sum(imbalances) / n
    slope = sum((i - x_mean) * (im - y_mean) for i, im in enumerate(imbalances))
    slope /= max(sum((i - x_mean) ** 2 for i in range(n)), 0.001)

    # Combined signal
    signal = weighted_avg + slope * 3  # amplify trending signals

    if signal > 0.2:
        trend = "persistent_buying"
    elif signal < -0.2:
        trend = "persistent_selling"
    else:
        trend = "neutral"

    return {
        "trend": trend,
        "signal": round(signal, 3),
        "weighted_imbalance": round(weighted_avg, 3),
        "slope": round(slope, 4),
        "n_snapshots": len(imbalances),
    }
