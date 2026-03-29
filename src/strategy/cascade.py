"""Information cascade and herd behavior detection.

Detects when market price moves are driven by herding rather than
genuine information, then generates contrarian signals.

Research: Cascades in prediction markets overshoot by 30-50% and
revert within 48 hours ~65-70% of the time.
"""

from __future__ import annotations

import structlog
from dataclasses import dataclass

log = structlog.get_logger()


@dataclass
class CascadeSignal:
    market_id: str
    cascade_probability: float  # 0-1
    direction: str  # "up" or "down"
    price_change: float
    volume_spike: float
    has_news: bool
    contrarian_side: str  # BUY_YES or BUY_NO
    estimated_overshoot: float
    confidence: float


def detect_cascade(
    current_price: float,
    price_history: list[float],
    volume_history: list[float],
    has_fundamental_news: bool = False,
    window: int = 24,
) -> dict:
    """Detect potential information cascade from price/volume data.

    A cascade is characterized by:
    1. Rapid price movement (>10% in window)
    2. Volume spike (>3x average)
    3. NO fundamental news (movement without cause)
    4. Accelerating momentum pattern
    """
    if len(price_history) < 3 or len(volume_history) < 3:
        return {"cascade_probability": 0, "detected": False}

    recent_prices = price_history[-window:] if len(price_history) >= window else price_history
    recent_volumes = volume_history[-window:] if len(volume_history) >= window else volume_history

    # Price change in window
    price_change = current_price - recent_prices[0]
    abs_change = abs(price_change)

    # Volume spike
    avg_volume = sum(recent_volumes[:-1]) / max(len(recent_volumes) - 1, 1)
    current_volume = recent_volumes[-1] if recent_volumes else 0
    volume_spike = current_volume / max(avg_volume, 0.01)

    # Momentum acceleration: each step bigger than the last
    accelerating = False
    if len(recent_prices) >= 4:
        changes = [recent_prices[i+1] - recent_prices[i] for i in range(len(recent_prices)-1)]
        last_3 = changes[-3:]
        same_dir = all(c > 0 for c in last_3) or all(c < 0 for c in last_3)
        accel = abs(last_3[-1]) > abs(last_3[-2]) > abs(last_3[-3]) if len(last_3) == 3 else False
        accelerating = same_dir and accel

    # Score cascade probability
    score = 0.0
    if abs_change > 0.10:
        score += 0.3
    elif abs_change > 0.05:
        score += 0.15
    if volume_spike > 3.0:
        score += 0.2
    elif volume_spike > 2.0:
        score += 0.1
    if not has_fundamental_news:
        score += 0.3  # No news = strong cascade signal
    if accelerating:
        score += 0.2

    score = min(score, 1.0)
    direction = "up" if price_change > 0 else "down"

    return {
        "cascade_probability": score,
        "detected": score > 0.5,
        "direction": direction,
        "price_change": price_change,
        "abs_change": abs_change,
        "volume_spike": volume_spike,
        "accelerating": accelerating,
        "has_news": has_fundamental_news,
    }


def contrarian_signal(
    cascade: dict,
    current_price: float,
    market_id: str = "",
) -> CascadeSignal | None:
    """Generate a contrarian trading signal from a detected cascade.

    Estimates overshoot at 35% of total move (conservative).
    Only triggers when cascade_probability > 0.6.
    """
    if cascade["cascade_probability"] < 0.6:
        return None

    price_change = cascade["price_change"]
    estimated_overshoot = abs(price_change) * 0.35

    # Trade against the cascade direction
    if cascade["direction"] == "up":
        contrarian_side = "BUY_NO"
    else:
        contrarian_side = "BUY_YES"

    confidence = cascade["cascade_probability"] * 0.7  # Discount confidence

    signal = CascadeSignal(
        market_id=market_id,
        cascade_probability=cascade["cascade_probability"],
        direction=cascade["direction"],
        price_change=price_change,
        volume_spike=cascade["volume_spike"],
        has_news=cascade["has_news"],
        contrarian_side=contrarian_side,
        estimated_overshoot=estimated_overshoot,
        confidence=confidence,
    )

    log.info(
        "cascade_contrarian_signal",
        market=market_id[:20],
        direction=cascade["direction"],
        overshoot=f"{estimated_overshoot:.1%}",
        contrarian=contrarian_side,
    )
    return signal


def detect_anchoring(current_price: float, anchor_values: list[float] = None) -> dict:
    """Detect if price is anchored to common salient values.

    Common anchors: 0.50 (coin flip), 0.33/0.67 (1/3, 2/3),
    round numbers, recent poll numbers.
    """
    if anchor_values is None:
        anchor_values = [0.25, 0.33, 0.50, 0.67, 0.75]

    for anchor in anchor_values:
        distance = abs(current_price - anchor)
        if distance < 0.03:
            return {
                "anchored": True,
                "anchor_value": anchor,
                "distance": distance,
                "warning": f"Price may be anchored to {anchor:.0%} rather than reflecting fundamentals",
            }
    return {"anchored": False}
