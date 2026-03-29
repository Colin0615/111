"""Bayesian belief updater for sequential evidence integration.

Maintains explicit probability priors and updates via likelihood ratios
as new evidence arrives. Prevents overreaction to single data points
and underreaction to cumulative evidence.
"""

from __future__ import annotations

import math
import structlog
from dataclasses import dataclass, field
from datetime import datetime, timezone

log = structlog.get_logger()


@dataclass
class Evidence:
    description: str
    likelihood_ratio: float  # P(evidence|YES) / P(evidence|NO)
    source_reliability: float  # 0-1, discounts the LR
    timestamp: str = ""

    @property
    def adjusted_lr(self) -> float:
        """Shrink LR toward 1.0 based on source reliability."""
        log_lr = math.log(max(self.likelihood_ratio, 0.01))
        adjusted = log_lr * self.source_reliability
        return math.exp(adjusted)


@dataclass
class BayesianModel:
    prior: float
    evidence_history: list[Evidence] = field(default_factory=list)

    @property
    def posterior(self) -> float:
        """Apply all evidence to compute current posterior probability."""
        odds = self.prior / (1 - self.prior) if self.prior < 1 else 999
        for e in self.evidence_history:
            odds *= e.adjusted_lr
        return odds / (1 + odds)

    def add_evidence(self, description: str, likelihood_ratio: float,
                     source_reliability: float = 0.8) -> float:
        """Add a piece of evidence and return updated posterior."""
        e = Evidence(
            description=description,
            likelihood_ratio=likelihood_ratio,
            source_reliability=source_reliability,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self.evidence_history.append(e)
        post = self.posterior
        log.info("bayesian_update",
                 evidence=description[:50],
                 lr=f"{likelihood_ratio:.2f}",
                 adjusted_lr=f"{e.adjusted_lr:.2f}",
                 posterior=f"{post:.1%}")
        return post

    def to_dict(self) -> dict:
        return {
            "prior": self.prior,
            "posterior": self.posterior,
            "evidence_count": len(self.evidence_history),
            "evidence": [
                {"desc": e.description, "lr": e.likelihood_ratio,
                 "reliability": e.source_reliability, "adjusted_lr": e.adjusted_lr}
                for e in self.evidence_history
            ],
        }


# Common likelihood ratio estimates for prediction markets
LR_GUIDES = {
    # News impact on YES probability
    "strong_positive_news": 3.0,      # Major positive development
    "moderate_positive_news": 1.8,    # Meaningful but not decisive
    "weak_positive_news": 1.2,        # Minor positive signal
    "neutral_news": 1.0,              # No impact
    "weak_negative_news": 0.8,        # Minor negative signal
    "moderate_negative_news": 0.55,   # Meaningful negative
    "strong_negative_news": 0.33,     # Major negative development

    # Source reliability presets
    "official_source": 0.95,          # Government, court, exchange
    "major_media": 0.80,             # Reuters, AP, Bloomberg
    "analyst_opinion": 0.60,         # Expert but subjective
    "social_media": 0.40,            # Twitter, Reddit
    "rumor": 0.20,                    # Unverified
}


def estimate_lr_from_ai(
    news_summary: str,
    market_question: str,
    ai_client,
    model: str = "claude-haiku-4-5-20251001",
) -> tuple[float, float]:
    """Use AI to estimate the likelihood ratio for a piece of evidence.

    Returns (likelihood_ratio, source_reliability).
    """
    prompt = f"""You are a Bayesian analyst. Given this news and market question,
estimate the likelihood ratio: how much more likely is this news if YES is true
versus if NO is true?

Market: {market_question}
News: {news_summary}

Output ONLY JSON:
{{"likelihood_ratio": <float, e.g. 1.0=neutral, 2.0=2x more likely if YES, 0.5=2x more likely if NO>,
  "source_reliability": <float 0-1, how reliable is this source>,
  "reasoning": "<brief>"}}
"""
    try:
        response = ai_client.messages.create(
            model=model,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        from src.analysis.ai_analyzer import _parse_json_from_response
        result = _parse_json_from_response(response.content[0].text)
        lr = float(result.get("likelihood_ratio", 1.0))
        reliability = float(result.get("source_reliability", 0.5))
        # Clamp to reasonable range
        lr = max(0.1, min(10.0, lr))
        reliability = max(0.1, min(1.0, reliability))
        return lr, reliability
    except Exception as e:
        log.warning("lr_estimation_failed", error=str(e))
        return 1.0, 0.5
