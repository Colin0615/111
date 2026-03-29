"""AI-powered market analysis using Claude API.

Two modes:
- Quick scan (Haiku): cheap, fast, used for daily scans of many markets
- Deep analysis (Sonnet): expensive, thorough, used for high-edge opportunities
"""

from __future__ import annotations

import json
import structlog
from datetime import datetime, timezone
from typing import Optional

import anthropic

from src.core.config import config
from src.strategy.calibration import calibrate_probability, record_prediction

log = structlog.get_logger()

_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.ai.anthropic_api_key)
    return _client


QUICK_SCAN_PROMPT = """\
You are a prediction market analyst. Evaluate this market concisely.

Market: {question}
Current YES price: ${yes_price:.2f} (market implies {yes_price_pct:.0f}% probability)
Current NO price: ${no_price:.2f}
Category: {category}
Closes: {end_date}
Description: {description}

{news_section}

Output ONLY valid JSON (no markdown, no explanation outside JSON):
{{
  "yes_probability": <your estimate 0.00-1.00>,
  "confidence": <1-10>,
  "key_factors": ["factor1", "factor2", "factor3"],
  "recommendation": "BUY_YES" | "BUY_NO" | "SKIP",
  "reasoning": "<one paragraph>"
}}
"""

DEEP_ANALYSIS_PROMPT = """\
You are a superforecaster applying the Tetlock methodology for prediction markets.
Your estimates are well-calibrated: when you say 70%, events happen ~70% of the time.
You systematically avoid overconfidence, anchoring, and confirmation bias.

## Market Information
Question: {question}
YES price: ${yes_price:.2f} (market implies {yes_price_pct:.0f}% probability)
NO price: ${no_price:.2f}
24h Volume: ${volume_24h:,.0f}
Category: {category}
Closes: {end_date}
Description: {description}

## Recent News
{news_section}

## Superforecaster Analysis Framework (follow ALL steps)

### Step 1: OUTSIDE VIEW (Base Rate)
What is the historical base rate for this type of event? How often do similar things happen?
Start here BEFORE looking at specifics. Anchor to the base rate first.

### Step 2: INSIDE VIEW (Specific Factors)
What specific factors make THIS case different from the base rate?
List factors pushing toward YES and factors pushing toward NO.

### Step 3: SYNTHESIS
Combine outside and inside views. Adjust from the base rate based on
the strength of specific evidence. Small adjustments unless evidence is very strong.

### Step 4: RED TEAM (Why You Might Be Wrong)
- What would change your mind?
- What information are you missing?
- Why might the market be right and you wrong?
- Are you being anchored by the current market price?

### Step 5: CALIBRATION CHECK
- Is your confidence justified by the evidence quality?
- Would you bet real money at these odds?
- Are you in the 30-70% zone where most uncertain events fall?

### Step 6: MARKET INEFFICIENCY CHECK
- Why would the market misprice this?
- Is there a structural reason (low liquidity, new market, anchoring)?
- Or is the market efficient and there is no edge?

## Output
Provide your full analysis then output this JSON block (MUST be valid JSON):
```json
{{
  "yes_probability": <your calibrated estimate 0.00-1.00>,
  "confidence": <1-10, where 10 = extremely confident>,
  "base_rate": <historical base rate if known, else null>,
  "arguments_yes": ["arg1", "arg2", "arg3"],
  "arguments_no": ["arg1", "arg2", "arg3"],
  "market_blind_spots": ["what the market might be missing"],
  "why_market_might_be_right": ["reason1", "reason2"],
  "recommendation": "BUY_YES" | "BUY_NO" | "SKIP",
  "position_conviction": "HIGH" | "MEDIUM" | "LOW",
  "reasoning": "<detailed reasoning paragraph>"
}}
```
"""


def _build_news_section(news: list[dict]) -> str:
    if not news:
        return "No recent news available."
    lines = []
    for i, article in enumerate(news[:10], 1):
        title = article.get("title", "No title")
        source = article.get("source", "Unknown")
        published = article.get("published", "")
        snippet = article.get("content", "")[:300]
        lines.append(f"{i}. [{source}] {title} ({published})\n   {snippet}")
    return "\n".join(lines)


def _parse_json_from_response(text: str) -> dict:
    """Extract JSON from Claude's response, handling markdown code blocks."""
    # Try direct JSON parse first
    text = text.strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    # Look for JSON in code blocks
    import re
    patterns = [
        r"```json\s*\n(.*?)\n```",
        r"```\s*\n(.*?)\n```",
        r"\{[^{}]*\"yes_probability\"[^{}]*\}",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                candidate = match.group(1) if match.lastindex else match.group(0)
                return json.loads(candidate)
            except (json.JSONDecodeError, IndexError):
                continue

    log.warning("failed_to_parse_json", response_preview=text[:200])
    return {
        "yes_probability": 0.5,
        "confidence": 1,
        "key_factors": ["parse_error"],
        "recommendation": "SKIP",
        "reasoning": f"Failed to parse AI response: {text[:200]}",
    }


async def quick_scan(
    market: dict,
    news: Optional[list[dict]] = None,
) -> dict:
    """Fast, cheap analysis using Haiku. Returns analysis dict."""
    news_section = _build_news_section(news or [])
    prompt = QUICK_SCAN_PROMPT.format(
        question=market["question"],
        yes_price=market.get("yes_price", 0.5),
        yes_price_pct=market.get("yes_price", 0.5) * 100,
        no_price=market.get("no_price", 0.5),
        category=market.get("category", "unknown"),
        end_date=market.get("end_date", "unknown"),
        description=(market.get("description", "") or "")[:500],
        news_section=news_section,
    )

    client = _get_client()
    response = client.messages.create(
        model=config.ai.fast_model,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )

    result = _parse_json_from_response(response.content[0].text)
    ai_prob = float(result.get("yes_probability", 0.5))
    market_price = market.get("yes_price", 0.5)

    return {
        "condition_id": market["condition_id"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": config.ai.fast_model,
        "ai_probability": ai_prob,
        "confidence": float(result.get("confidence", 5)),
        "market_price": market_price,
        "edge": ai_prob - market_price,
        "reasoning": result.get("reasoning", ""),
        "recommendation": result.get("recommendation", "SKIP"),
        "news_context": news_section[:500] if news else "",
        "raw_result": result,
    }


async def deep_analysis(
    market: dict,
    news: Optional[list[dict]] = None,
) -> dict:
    """Thorough analysis using Sonnet. Use for high-edge opportunities."""
    news_section = _build_news_section(news or [])
    prompt = DEEP_ANALYSIS_PROMPT.format(
        question=market["question"],
        yes_price=market.get("yes_price", 0.5),
        yes_price_pct=market.get("yes_price", 0.5) * 100,
        no_price=market.get("no_price", 0.5),
        volume_24h=market.get("volume_24h", 0),
        category=market.get("category", "unknown"),
        end_date=market.get("end_date", "unknown"),
        description=(market.get("description", "") or "")[:1000],
        news_section=news_section,
    )

    client = _get_client()
    response = client.messages.create(
        model=config.ai.strong_model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    full_text = response.content[0].text
    result = _parse_json_from_response(full_text)
    raw_prob = float(result.get("yes_probability", 0.5))
    market_price = market.get("yes_price", 0.5)

    # Apply calibration correction
    ai_prob = calibrate_probability(raw_prob)

    # Record prediction for future calibration tracking
    try:
        record_prediction(market["condition_id"], ai_prob, config.ai.strong_model)
    except Exception as e:
        log.warning("calibration_record_failed", error=str(e))

    log.info("deep_analysis_calibrated",
             raw_prob=f"{raw_prob:.1%}",
             calibrated=f"{ai_prob:.1%}",
             market=f"{market_price:.1%}")

    return {
        "condition_id": market["condition_id"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": config.ai.strong_model,
        "ai_probability": ai_prob,
        "raw_probability": raw_prob,
        "confidence": float(result.get("confidence", 5)),
        "market_price": market_price,
        "edge": ai_prob - market_price,
        "reasoning": result.get("reasoning", ""),
        "recommendation": result.get("recommendation", "SKIP"),
        "news_context": news_section[:500] if news else "",
        "arguments_yes": result.get("arguments_yes", []),
        "arguments_no": result.get("arguments_no", []),
        "market_blind_spots": result.get("market_blind_spots", []),
        "why_market_might_be_right": result.get("why_market_might_be_right", []),
        "base_rate": result.get("base_rate"),
        "position_conviction": result.get("position_conviction", "LOW"),
        "full_response": full_text,
        "raw_result": result,
    }
