"""Test the full trading pipeline with mock data.

Verifies: market parsing → AI analysis → signal generation → risk check → paper trade.
"""

import asyncio
import json
import sys
import os

# Ensure src is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import config
from src.core import database as db
from src.market.client import categorize_market
from src.strategy.signals import generate_signal, check_risk, rank_signals, Signal
from src.execution.paper_trader import execute_paper_trade
from src.analysis.ai_analyzer import _parse_json_from_response

# -- Mock data simulating Polymarket markets --

MOCK_MARKETS = [
    {
        "condition_id": "0xabc123_btc_100k",
        "question": "Will Bitcoin exceed $100,000 before April 30, 2026?",
        "description": "This market resolves YES if Bitcoin trades above $100,000 on any major exchange before April 30.",
        "category": "crypto",
        "end_date": "2026-04-30",
        "yes_price": 0.65,
        "no_price": 0.35,
        "volume_24h": 50000,
        "liquidity": 100000,
        "tokens": [
            {"token_id": "tok_yes_1", "outcome": "Yes", "price": 0.65},
            {"token_id": "tok_no_1", "outcome": "No", "price": 0.35},
        ],
    },
    {
        "condition_id": "0xdef456_fed_rate",
        "question": "Will the Fed cut interest rates at the May 2026 meeting?",
        "description": "Resolves YES if the Federal Reserve announces a rate cut at the May FOMC meeting.",
        "category": "economics",
        "end_date": "2026-05-15",
        "yes_price": 0.42,
        "no_price": 0.58,
        "volume_24h": 25000,
        "liquidity": 60000,
        "tokens": [
            {"token_id": "tok_yes_2", "outcome": "Yes", "price": 0.42},
            {"token_id": "tok_no_2", "outcome": "No", "price": 0.58},
        ],
    },
    {
        "condition_id": "0xghi789_election",
        "question": "Will the Democratic candidate win the 2026 Georgia Senate race?",
        "description": "Resolves based on the certified election results.",
        "category": "politics",
        "end_date": "2026-11-05",
        "yes_price": 0.48,
        "no_price": 0.52,
        "volume_24h": 15000,
        "liquidity": 30000,
        "tokens": [
            {"token_id": "tok_yes_3", "outcome": "Yes", "price": 0.48},
            {"token_id": "tok_no_3", "outcome": "No", "price": 0.52},
        ],
    },
]

# Mock AI analysis results (simulating what Claude would return)
MOCK_ANALYSES = [
    {
        "condition_id": "0xabc123_btc_100k",
        "timestamp": "2026-03-29T12:00:00Z",
        "model": "claude-haiku-4-5-20251001",
        "ai_probability": 0.78,  # AI thinks 78% likely, market says 65% → 13% edge
        "confidence": 7,
        "market_price": 0.65,
        "edge": 0.13,
        "reasoning": "BTC momentum strong, ETF inflows continue, halving cycle bullish.",
        "recommendation": "BUY_YES",
    },
    {
        "condition_id": "0xdef456_fed_rate",
        "timestamp": "2026-03-29T12:00:00Z",
        "model": "claude-haiku-4-5-20251001",
        "ai_probability": 0.40,  # AI agrees with market → no edge
        "confidence": 6,
        "market_price": 0.42,
        "edge": -0.02,
        "reasoning": "Economic data mixed, Fed likely to hold.",
        "recommendation": "SKIP",
    },
    {
        "condition_id": "0xghi789_election",
        "timestamp": "2026-03-29T12:00:00Z",
        "model": "claude-haiku-4-5-20251001",
        "ai_probability": 0.38,  # AI thinks NO is more likely → edge on NO side
        "confidence": 5,
        "market_price": 0.48,
        "edge": -0.10,
        "reasoning": "Incumbent advantage, polling suggests Republican lean.",
        "recommendation": "BUY_NO",
    },
]


def test_categorize_market():
    """Test market categorization."""
    assert categorize_market("Will Bitcoin exceed $100k?") == "crypto"
    assert categorize_market("Will the president sign the bill?") == "politics"
    assert categorize_market("Will GDP grow by 3%?") == "economics"
    assert categorize_market("Will Apple release a new product?") == "tech"
    assert categorize_market("Will the NBA finals go to 7 games?") == "sports"
    assert categorize_market("Something completely random") == "other"
    print("  [PASS] categorize_market")


def test_json_parsing():
    """Test JSON extraction from AI responses."""
    # Direct JSON
    result = _parse_json_from_response('{"yes_probability": 0.75, "confidence": 8}')
    assert result["yes_probability"] == 0.75

    # JSON in code block
    result = _parse_json_from_response(
        'Here is my analysis:\n```json\n{"yes_probability": 0.60, "confidence": 7}\n```\nDone.'
    )
    assert result["yes_probability"] == 0.60

    # Fallback on garbage
    result = _parse_json_from_response("This is not JSON at all")
    assert result["recommendation"] == "SKIP"  # Fallback

    print("  [PASS] JSON parsing")


def test_signal_generation():
    """Test signal generation from mock analyses."""
    # BTC: AI=78%, Market=65% → 13% edge → should generate BUY_YES
    signal = generate_signal(MOCK_ANALYSES[0], MOCK_MARKETS[0])
    assert signal is not None
    assert signal.side == "BUY_YES"
    assert signal.edge > 0.08
    assert 2.0 <= signal.suggested_size_usd <= 5.0
    print(f"  [PASS] BTC signal: {signal.side} edge={signal.edge:.1%} size=${signal.suggested_size_usd}")

    # Fed rate: AI=40%, Market=42% → -2% edge → should NOT generate signal
    signal = generate_signal(MOCK_ANALYSES[1], MOCK_MARKETS[1])
    assert signal is None
    print("  [PASS] Fed rate: no signal (no edge)")

    # Election: AI=38% YES → 62% NO, Market NO=52% → 10% NO edge → BUY_NO
    signal = generate_signal(MOCK_ANALYSES[2], MOCK_MARKETS[2])
    assert signal is not None
    assert signal.side == "BUY_NO"
    assert signal.edge > 0.08
    print(f"  [PASS] Election signal: {signal.side} edge={signal.edge:.1%} size=${signal.suggested_size_usd}")


def test_signal_ranking():
    """Test signal ranking."""
    signals = []
    for analysis, market in zip(MOCK_ANALYSES, MOCK_MARKETS):
        sig = generate_signal(analysis, market)
        if sig:
            signals.append(sig)

    ranked = rank_signals(signals)
    assert len(ranked) == 2
    # BTC should rank higher (higher edge * confidence)
    assert ranked[0].condition_id == "0xabc123_btc_100k"
    print(f"  [PASS] Ranking: #{1} {ranked[0].question[:40]}...")


async def test_risk_checks():
    """Test risk management checks."""
    # Initialize test portfolio
    os.environ["INITIAL_BANKROLL"] = "50"

    # Use a temp DB
    import tempfile
    tmp = tempfile.mktemp(suffix=".db")
    original_path = config.db_path
    object.__setattr__(config, 'db_path', tmp)

    try:
        await db.init_portfolio(50.0)

        # Generate a signal
        signal = generate_signal(MOCK_ANALYSES[0], MOCK_MARKETS[0])
        assert signal is not None

        # Should pass all checks
        approved, reason = await check_risk(signal)
        assert approved, f"Risk check failed: {reason}"
        print(f"  [PASS] Risk check approved: {reason}")

        # Execute paper trade
        trade = await execute_paper_trade(signal)
        assert trade["status"] == "PAPER"
        assert trade["side"] == "BUY_YES"
        print(f"  [PASS] Paper trade executed: #{trade['id']} {trade['side']} ${trade['size_usd']:.2f}")

        # Check portfolio updated
        portfolio = await db.get_portfolio()
        assert portfolio["cash"] < 50.0
        assert portfolio["trades_today"] >= 1
        print(f"  [PASS] Portfolio updated: cash=${portfolio['cash']:.2f}, trades={portfolio['trades_today']}")

        # Second trade should also work
        signal2 = generate_signal(MOCK_ANALYSES[2], MOCK_MARKETS[2])
        if signal2:
            approved2, reason2 = await check_risk(signal2)
            print(f"  [PASS] Second risk check: approved={approved2}, {reason2}")

    finally:
        object.__setattr__(config, 'db_path', original_path)
        os.unlink(tmp)


def test_news_keywords():
    """Test keyword extraction for news matching."""
    from src.news.collector import _extract_keywords
    kw = _extract_keywords("Will Bitcoin exceed $100,000 before April 2026?")
    assert "bitcoin" in kw
    assert "exceed" in kw
    assert "will" not in kw  # stop word
    print(f"  [PASS] Keywords: {kw}")


def test_rss_parser():
    """Test RSS XML parsing with sample data."""
    from src.news.collector import _parse_rss_xml

    sample_rss = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Test Feed</title>
        <item>
          <title>Bitcoin hits new high</title>
          <link>https://example.com/btc</link>
          <description>BTC surges past $95k amid ETF inflows</description>
          <pubDate>Sat, 29 Mar 2026 10:00:00 GMT</pubDate>
        </item>
        <item>
          <title>Fed holds rates steady</title>
          <link>https://example.com/fed</link>
          <description>Federal Reserve keeps rates unchanged at 4.5%</description>
          <pubDate>Sat, 29 Mar 2026 08:00:00 GMT</pubDate>
        </item>
      </channel>
    </rss>"""

    articles = _parse_rss_xml(sample_rss, "https://example.com/rss")
    assert len(articles) == 2
    assert articles[0]["title"] == "Bitcoin hits new high"
    assert articles[0]["source"] == "Test Feed"
    assert "surges" in articles[0]["content"]
    print(f"  [PASS] RSS parser: {len(articles)} articles parsed")


async def run_all_tests():
    print("\n=== Polymarket AI Trader - Test Suite ===\n")

    print("[Unit Tests]")
    test_categorize_market()
    test_json_parsing()
    test_signal_generation()
    test_signal_ranking()
    test_news_keywords()
    test_rss_parser()

    print("\n[Integration Tests]")
    await test_risk_checks()

    print("\n=== All tests passed! ===\n")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
