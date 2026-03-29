"""Multi-model ensemble prediction with extremization.

Research basis: Satopaa et al. (2014) - averaging multiple forecasters
regresses toward 0.5. Extremization corrects this. Weighting by historical
Brier score outperforms equal weighting.
"""

from __future__ import annotations

import math
import structlog
from dataclasses import dataclass
from typing import Optional

import anthropic

from src.core.config import config

log = structlog.get_logger()


@dataclass
class ModelPrediction:
    model: str
    probability: float
    confidence: float
    reasoning: str
    weight: float = 1.0  # calibration-derived weight


def extremize(p: float, d: float = 1.5) -> float:
    """Push probability away from 0.5 using log-odds scaling.

    d > 1 extremizes (recommended 1.3-2.0 for ensemble averaging).
    d = 1 is identity. d < 1 shrinks toward 0.5.
    """
    if p <= 0.01 or p >= 0.99:
        return p
    log_odds = math.log(p / (1 - p))
    adjusted = log_odds * d
    return 1 / (1 + math.exp(-adjusted))


ENSEMBLE_PROMPT = """\
You are a {perspective} analyzing a prediction market.

Question: {question}
Current market price: {yes_price:.1%} YES
Description: {description}

{news_section}

Think from your specific perspective as a {perspective}. Then provide:
1. Your probability estimate for YES (0.00-1.00)
2. Confidence in your estimate (1-10)
3. Brief reasoning (2-3 sentences)

Output ONLY valid JSON:
{{"probability": 0.XX, "confidence": N, "reasoning": "..."}}
"""

# Different reasoning perspectives to reduce correlated errors
PERSPECTIVES = [
    "base-rate statistician who focuses on historical frequencies of similar events",
    "domain expert who deeply understands the specific subject matter",
    "contrarian analyst who considers why the market consensus might be wrong",
]


async def ensemble_predict(
    market: dict,
    news_context: str = "",
    model: str = "",
) -> dict:
    """Get ensemble prediction from multiple reasoning perspectives.

    Uses a single LLM with diverse prompting (cheaper than multi-model
    but captures most of the diversification benefit).
    """
    if not model:
        model = config.ai.strong_model

    client = anthropic.Anthropic(api_key=config.ai.anthropic_api_key)
    predictions: list[ModelPrediction] = []

    for perspective in PERSPECTIVES:
        prompt = ENSEMBLE_PROMPT.format(
            perspective=perspective,
            question=market.get("question", ""),
            yes_price=market.get("yes_price", 0.5),
            description=(market.get("description", "") or "")[:500],
            news_section=news_context or "No recent news available.",
        )

        try:
            response = client.messages.create(
                model=model,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            from src.analysis.ai_analyzer import _parse_json_from_response
            result = _parse_json_from_response(response.content[0].text)

            predictions.append(ModelPrediction(
                model=f"{model}:{perspective[:20]}",
                probability=float(result.get("probability", 0.5)),
                confidence=float(result.get("confidence", 5)),
                reasoning=result.get("reasoning", ""),
            ))
        except Exception as e:
            log.warning("ensemble_perspective_failed", perspective=perspective[:20], error=str(e))

    if not predictions:
        return {"ensemble_probability": 0.5, "confidence": 1, "predictions": []}

    # Weighted average (by confidence)
    total_weight = sum(p.confidence for p in predictions)
    if total_weight == 0:
        raw_avg = sum(p.probability for p in predictions) / len(predictions)
    else:
        raw_avg = sum(p.probability * p.confidence for p in predictions) / total_weight

    # Extremize to correct for averaging regression toward 0.5
    ensemble_prob = extremize(raw_avg, d=1.5)

    # Ensemble confidence = average confidence adjusted by agreement
    probs = [p.probability for p in predictions]
    spread = max(probs) - min(probs) if len(probs) > 1 else 0
    agreement_bonus = max(0, 1 - spread * 5)  # bonus when predictions agree
    avg_confidence = sum(p.confidence for p in predictions) / len(predictions)
    ensemble_confidence = min(avg_confidence * (0.8 + 0.2 * agreement_bonus), 10)

    log.info(
        "ensemble_prediction",
        raw_avg=f"{raw_avg:.1%}",
        extremized=f"{ensemble_prob:.1%}",
        spread=f"{spread:.1%}",
        confidence=f"{ensemble_confidence:.1f}",
        n_perspectives=len(predictions),
    )

    return {
        "ensemble_probability": ensemble_prob,
        "raw_average": raw_avg,
        "confidence": ensemble_confidence,
        "predictions": [
            {"model": p.model, "probability": p.probability,
             "confidence": p.confidence, "reasoning": p.reasoning}
            for p in predictions
        ],
        "spread": spread,
        "extremization_factor": 1.5,
    }
