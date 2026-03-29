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


def test_ensemble_extremize():
    """Test probability extremization."""
    from src.strategy.ensemble import extremize
    # Identity-ish at 0.5
    assert abs(extremize(0.5) - 0.5) < 0.001
    # Extremize pushes away from 0.5
    assert extremize(0.6) > 0.6
    assert extremize(0.4) < 0.4
    # Boundary values stay put
    assert extremize(0.01) == 0.01
    assert extremize(0.99) == 0.99
    print("  [PASS] extremize")


def test_cascade_detection():
    """Test cascade detection logic."""
    from src.strategy.cascade import detect_cascade, contrarian_signal

    # Strong cascade: big price move, volume spike, no news, accelerating
    result = detect_cascade(
        current_price=0.75,
        price_history=[0.50, 0.55, 0.60, 0.65, 0.68, 0.72, 0.75],
        volume_history=[100, 110, 120, 130, 200, 400, 800],
        has_fundamental_news=False,
    )
    assert result["detected"] is True
    assert result["cascade_probability"] > 0.5
    assert result["direction"] == "up"
    print(f"  [PASS] cascade detected: prob={result['cascade_probability']:.2f}, dir={result['direction']}")

    # Contrarian signal
    signal = contrarian_signal(result, current_price=0.75, market_id="test_market")
    assert signal is not None
    assert signal.contrarian_side == "BUY_NO"  # Counter to upward cascade
    print(f"  [PASS] contrarian signal: {signal.contrarian_side}, overshoot={signal.estimated_overshoot:.1%}")

    # No cascade: stable prices
    result2 = detect_cascade(
        current_price=0.50,
        price_history=[0.49, 0.50, 0.50, 0.51, 0.50],
        volume_history=[100, 110, 105, 100, 100],
        has_fundamental_news=False,
    )
    assert result2["detected"] is False
    print("  [PASS] no cascade for stable market")


def test_orderbook_analysis():
    """Test order book analysis."""
    from src.strategy.orderbook import analyze_orderbook

    # Bullish book: more bid depth
    book = {
        "bids": [
            {"price": "0.50", "size": "500"},
            {"price": "0.49", "size": "300"},
            {"price": "0.48", "size": "200"},
        ],
        "asks": [
            {"price": "0.51", "size": "100"},
            {"price": "0.52", "size": "50"},
            {"price": "0.53", "size": "30"},
        ],
    }
    signal = analyze_orderbook(book)
    assert signal.depth_imbalance > 0  # More bids than asks
    assert signal.signal_direction == "bullish"
    assert signal.is_liquid  # Good spread and depth
    print(f"  [PASS] orderbook: imbalance={signal.depth_imbalance}, direction={signal.signal_direction}")

    # Test wall detection
    book_with_wall = {
        "bids": [
            {"price": "0.50", "size": "100"},
            {"price": "0.49", "size": "100"},
            {"price": "0.48", "size": "1000"},  # Wall
        ],
        "asks": [
            {"price": "0.51", "size": "100"},
        ],
    }
    signal2 = analyze_orderbook(book_with_wall)
    assert len(signal2.walls) > 0
    assert signal2.walls[0]["side"] == "bid"
    print(f"  [PASS] wall detected at {signal2.walls[0]['price']} (size={signal2.walls[0]['size']})")


def test_bayesian_model():
    """Test Bayesian belief updating."""
    from src.strategy.bayesian import BayesianModel, Evidence

    model = BayesianModel(prior=0.5)
    assert abs(model.posterior - 0.5) < 0.001

    # Add positive evidence
    post = model.add_evidence("Strong positive news", likelihood_ratio=3.0, source_reliability=0.8)
    assert post > 0.5
    print(f"  [PASS] Bayesian: prior=50% + positive news → posterior={post:.1%}")

    # Add negative evidence
    post2 = model.add_evidence("Negative development", likelihood_ratio=0.5, source_reliability=0.9)
    assert post2 < post  # Should decrease
    print(f"  [PASS] Bayesian: + negative news → posterior={post2:.1%}")

    # Source reliability shrinks LR toward 1.0
    e = Evidence("test", likelihood_ratio=4.0, source_reliability=0.5)
    assert e.adjusted_lr < 4.0 and e.adjusted_lr > 1.0
    print(f"  [PASS] LR shrinkage: raw=4.0, adjusted={e.adjusted_lr:.2f} (reliability=0.5)")


def test_portfolio_optimizer():
    """Test portfolio allocation optimization."""
    from src.strategy.portfolio import optimize_allocations

    signals = [
        {"condition_id": "m1", "category": "crypto", "edge": 0.15, "market_price": 0.60, "confidence": 8, "side": "BUY_YES"},
        {"condition_id": "m2", "category": "crypto", "edge": 0.12, "market_price": 0.40, "confidence": 7, "side": "BUY_YES"},
        {"condition_id": "m3", "category": "politics", "edge": 0.10, "market_price": 0.50, "confidence": 6, "side": "BUY_NO"},
    ]
    allocations = optimize_allocations(signals, current_positions=[], cash_available=50.0)

    assert len(allocations) > 0
    total = sum(a.adjusted_size for a in allocations)
    assert total <= 50.0  # Cannot exceed cash
    print(f"  [PASS] portfolio optimizer: {len(allocations)} allocations, total=${total:.2f}")

    for a in allocations:
        assert a.adjusted_size >= 2.0  # Min viable trade
        print(f"    {a.market_id}: kelly=${a.raw_kelly_size:.2f} → adjusted=${a.adjusted_size:.2f} ({a.reason})")


def test_calibration():
    """Test probability calibration (cold start)."""
    from src.strategy.calibration import calibrate_probability

    # With no data, should shrink toward 0.5 by 10%
    cal = calibrate_probability(0.80)
    assert abs(cal - (0.9 * 0.80 + 0.1 * 0.5)) < 0.001
    cal2 = calibrate_probability(0.20)
    assert abs(cal2 - (0.9 * 0.20 + 0.1 * 0.5)) < 0.001
    print(f"  [PASS] calibration cold start: 0.80 → {cal:.3f}, 0.20 → {cal2:.3f}")


def test_cascade_anchoring():
    """Test anchoring detection."""
    from src.strategy.cascade import detect_anchoring

    result = detect_anchoring(0.50)
    assert result["anchored"] is True
    assert result["anchor_value"] == 0.50
    print(f"  [PASS] anchoring detected at {result['anchor_value']}")

    result2 = detect_anchoring(0.63)
    assert result2["anchored"] is False
    print("  [PASS] no anchoring at 0.63")


async def run_all_tests():
    print("\n=== Polymarket AI Trader - Test Suite ===\n")

    print("[Unit Tests]")
    test_categorize_market()
    test_json_parsing()
    test_signal_generation()
    test_signal_ranking()
    test_news_keywords()
    test_rss_parser()

    print("\n[Advanced Strategy Tests]")
    test_ensemble_extremize()
    test_cascade_detection()
    test_orderbook_analysis()
    test_bayesian_model()
    test_portfolio_optimizer()
    test_calibration()
    test_cascade_anchoring()

    print("\n[Integration Tests]")
    await test_risk_checks()

    print("\n=== All tests passed! ===\n")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
