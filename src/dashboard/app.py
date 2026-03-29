"""Polymarket AI Trader - Web Dashboard.

A single-file FastAPI app with embedded HTML/CSS/JS frontend.
Run: python -m src.dashboard
Visit: http://localhost:8888
"""

from __future__ import annotations

import asyncio
import json
import traceback
from datetime import datetime, timezone

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route
from starlette.requests import Request

from src.core.config import config
from src.core import database as db
from src.market.client import fetch_active_markets, categorize_market
from src.analysis.ai_analyzer import quick_scan, deep_analysis
from src.news.collector import search_news_for_market
from src.strategy.signals import generate_signal, check_risk, rank_signals
from src.execution.paper_trader import execute_paper_trade, update_positions_pnl


# ── API Endpoints ─────────────────────────────────────────────

async def api_portfolio(request: Request) -> JSONResponse:
    portfolio = await db.get_portfolio()
    if not portfolio:
        await db.init_portfolio(config.trading.initial_bankroll)
        portfolio = await db.get_portfolio()
    positions = await update_positions_pnl()
    portfolio = await db.get_portfolio()
    return JSONResponse({
        "portfolio": portfolio,
        "positions": positions,
        "config": {
            "initial_bankroll": config.trading.initial_bankroll,
            "max_position_size": config.trading.max_position_size,
            "min_edge": config.trading.min_edge_threshold,
            "max_daily_trades": config.trading.max_daily_trades,
            "stop_loss_pct": config.trading.stop_loss_pct,
        },
    })


async def api_scan(request: Request) -> JSONResponse:
    top_n = int(request.query_params.get("limit", "15"))
    try:
        markets = await fetch_active_markets(limit=100, min_volume=100)
    except Exception as e:
        return JSONResponse({"error": f"Failed to fetch markets: {e}", "results": []}, status_code=502)

    for m in markets:
        if not m.get("category"):
            m["category"] = categorize_market(m["question"], m.get("description", ""))

    results = []
    for m in markets[:top_n]:
        try:
            news = await search_news_for_market(m)
            analysis = await quick_scan(m, news=news)
            await db.save_market(m)
            await db.save_analysis(analysis)
            signal = generate_signal(analysis, m)
            results.append({
                "market": m,
                "analysis": {k: v for k, v in analysis.items() if k != "raw_result"},
                "signal": {
                    "side": signal.side,
                    "edge": signal.edge,
                    "size": signal.suggested_size_usd,
                    "strength": signal.strength,
                    "confidence": signal.confidence,
                } if signal else None,
            })
        except Exception as e:
            results.append({
                "market": m,
                "analysis": {"error": str(e)},
                "signal": None,
            })

    results.sort(key=lambda r: abs(r["analysis"].get("edge", 0)) if "edge" in r["analysis"] else 0, reverse=True)
    return JSONResponse({"results": results, "total_scanned": len(markets)})


async def api_analyze(request: Request) -> JSONResponse:
    condition_id = request.query_params.get("id", "")
    if not condition_id:
        return JSONResponse({"error": "Missing 'id' parameter"}, status_code=400)

    try:
        markets = await fetch_active_markets(limit=200)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)

    market = next((m for m in markets if m.get("condition_id") == condition_id), None)
    if not market:
        return JSONResponse({"error": "Market not found"}, status_code=404)

    news = await search_news_for_market(market)
    analysis = await deep_analysis(market, news=news)
    await db.save_market(market)
    await db.save_analysis(analysis)
    signal = generate_signal(analysis, market)

    return JSONResponse({
        "market": market,
        "analysis": {k: v for k, v in analysis.items() if k not in ("raw_result", "full_response")},
        "signal": {
            "side": signal.side,
            "edge": signal.edge,
            "size": signal.suggested_size_usd,
            "strength": signal.strength,
        } if signal else None,
        "news_count": len(news),
    })


async def api_trade(request: Request) -> JSONResponse:
    body = await request.json()
    condition_id = body.get("condition_id")
    if not condition_id:
        return JSONResponse({"error": "Missing condition_id"}, status_code=400)

    # Get stored market and latest analysis
    markets = await db.get_active_markets()
    market = next((m for m in markets if m["condition_id"] == condition_id), None)
    if not market:
        return JSONResponse({"error": "Market not found in database. Run scan first."}, status_code=404)

    analyses = await db.get_recent_analyses(condition_id, limit=1)
    if not analyses:
        return JSONResponse({"error": "No analysis found. Scan or analyze first."}, status_code=404)

    analysis = analyses[0]
    signal = generate_signal(analysis, market)
    if not signal:
        return JSONResponse({"error": "No valid signal for this market (edge too low)."}, status_code=400)

    approved, reason = await check_risk(signal)
    if not approved:
        return JSONResponse({"error": f"Risk check failed: {reason}"}, status_code=400)

    trade = await execute_paper_trade(signal)
    return JSONResponse({"trade": trade, "message": "Paper trade executed!"})


async def api_history(request: Request) -> JSONResponse:
    limit = int(request.query_params.get("limit", "50"))
    trades = await db.get_trade_history(limit=limit)
    return JSONResponse({"trades": trades})


async def index(request: Request) -> HTMLResponse:
    return HTMLResponse(DASHBOARD_HTML)


# ── Routes ────────────────────────────────────────────────────

app = Starlette(
    routes=[
        Route("/", index),
        Route("/api/portfolio", api_portfolio),
        Route("/api/scan", api_scan),
        Route("/api/analyze", api_analyze),
        Route("/api/trade", api_trade, methods=["POST"]),
        Route("/api/history", api_history),
    ],
)

# ── Frontend HTML ─────────────────────────────────────────────

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Polymarket AI Trader</title>
<style>
  :root {
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface2: #242836;
    --border: #2e3348;
    --text: #e4e6f0;
    --text-dim: #8b8fa3;
    --accent: #6c5ce7;
    --green: #00d2a0;
    --red: #ff6b6b;
    --yellow: #ffd43b;
    --blue: #4dabf7;
    --radius: 12px;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
  }

  /* Header */
  .header {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 16px 32px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .header h1 {
    font-size: 20px;
    font-weight: 700;
    background: linear-gradient(135deg, var(--accent), var(--blue));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }
  .header-status {
    display: flex;
    gap: 24px;
    font-size: 13px;
  }
  .status-item { display: flex; align-items: center; gap: 6px; }
  .status-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--green);
    animation: pulse 2s infinite;
  }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }

  /* Layout */
  .container { max-width: 1400px; margin: 0 auto; padding: 24px; }

  /* Nav tabs */
  .nav { display: flex; gap: 8px; margin-bottom: 24px; }
  .nav-btn {
    background: var(--surface);
    border: 1px solid var(--border);
    color: var(--text-dim);
    padding: 10px 20px;
    border-radius: var(--radius);
    cursor: pointer;
    font-size: 14px;
    font-weight: 500;
    transition: all 0.2s;
  }
  .nav-btn:hover { background: var(--surface2); color: var(--text); }
  .nav-btn.active {
    background: var(--accent);
    border-color: var(--accent);
    color: white;
  }

  /* Cards */
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 20px;
  }
  .card-label { font-size: 12px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
  .card-value { font-size: 28px; font-weight: 700; }
  .card-sub { font-size: 13px; margin-top: 4px; }
  .positive { color: var(--green); }
  .negative { color: var(--red); }

  /* Table */
  .panel {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
    margin-bottom: 24px;
  }
  .panel-header {
    padding: 16px 20px;
    border-bottom: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .panel-title { font-size: 16px; font-weight: 600; }
  table { width: 100%; border-collapse: collapse; }
  th {
    text-align: left;
    padding: 10px 16px;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-dim);
    border-bottom: 1px solid var(--border);
    background: var(--surface2);
  }
  td {
    padding: 12px 16px;
    font-size: 13px;
    border-bottom: 1px solid var(--border);
  }
  tr:hover { background: var(--surface2); }
  tr:last-child td { border-bottom: none; }

  /* Badges */
  .badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 600;
  }
  .badge-green { background: rgba(0,210,160,0.15); color: var(--green); }
  .badge-red { background: rgba(255,107,107,0.15); color: var(--red); }
  .badge-yellow { background: rgba(255,212,59,0.15); color: var(--yellow); }
  .badge-blue { background: rgba(77,171,247,0.15); color: var(--blue); }
  .badge-dim { background: var(--surface2); color: var(--text-dim); }

  /* Buttons */
  .btn {
    padding: 8px 16px;
    border-radius: 8px;
    border: none;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
  }
  .btn-primary { background: var(--accent); color: white; }
  .btn-primary:hover { background: #5a4bd4; }
  .btn-success { background: var(--green); color: #0f1117; }
  .btn-success:hover { opacity: 0.9; }
  .btn-outline {
    background: transparent;
    border: 1px solid var(--border);
    color: var(--text-dim);
  }
  .btn-outline:hover { background: var(--surface2); color: var(--text); }
  .btn:disabled { opacity: 0.4; cursor: not-allowed; }

  /* Loading */
  .spinner {
    display: inline-block;
    width: 16px; height: 16px;
    border: 2px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    margin-right: 8px;
    vertical-align: middle;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* Section visibility */
  .section { display: none; }
  .section.active { display: block; }

  /* Edge bar */
  .edge-bar {
    display: inline-block;
    height: 6px;
    border-radius: 3px;
    min-width: 4px;
    max-width: 80px;
    vertical-align: middle;
    margin-left: 6px;
  }

  /* Analysis panel */
  .analysis-detail {
    background: var(--surface2);
    border-radius: var(--radius);
    padding: 20px;
    margin-top: 16px;
    line-height: 1.7;
  }
  .analysis-detail h3 { font-size: 15px; margin: 16px 0 8px; }
  .analysis-detail h3:first-child { margin-top: 0; }
  .analysis-detail ul { padding-left: 20px; }
  .analysis-detail li { margin: 4px 0; font-size: 13px; }

  /* Toast */
  .toast {
    position: fixed;
    bottom: 32px;
    right: 32px;
    padding: 14px 24px;
    border-radius: var(--radius);
    font-size: 14px;
    font-weight: 500;
    z-index: 1000;
    transform: translateY(100px);
    opacity: 0;
    transition: all 0.3s;
  }
  .toast.show { transform: translateY(0); opacity: 1; }
  .toast-success { background: var(--green); color: #0f1117; }
  .toast-error { background: var(--red); color: white; }

  /* Empty state */
  .empty {
    text-align: center;
    padding: 60px 20px;
    color: var(--text-dim);
  }
  .empty-icon { font-size: 48px; margin-bottom: 16px; opacity: 0.3; }
</style>
</head>
<body>

<div class="header">
  <h1>Polymarket AI Trader</h1>
  <div class="header-status">
    <div class="status-item"><div class="status-dot"></div> System Online</div>
    <div class="status-item" id="clock"></div>
  </div>
</div>

<div class="container">
  <div class="nav">
    <button class="nav-btn active" onclick="showSection('overview')">Overview</button>
    <button class="nav-btn" onclick="showSection('scan')">Market Scan</button>
    <button class="nav-btn" onclick="showSection('positions')">Positions</button>
    <button class="nav-btn" onclick="showSection('history')">History</button>
  </div>

  <!-- OVERVIEW -->
  <div id="section-overview" class="section active">
    <div class="cards" id="portfolio-cards"></div>
    <div class="panel">
      <div class="panel-header">
        <span class="panel-title">Open Positions</span>
        <button class="btn btn-outline" onclick="loadPortfolio()">Refresh</button>
      </div>
      <div id="positions-table-overview"></div>
    </div>
  </div>

  <!-- SCAN -->
  <div id="section-scan" class="section">
    <div style="display:flex; gap:12px; margin-bottom:20px; align-items:center;">
      <button class="btn btn-primary" id="scan-btn" onclick="runScan()">Scan Markets</button>
      <select id="scan-limit" class="btn btn-outline" style="padding:8px 12px;">
        <option value="10">Top 10</option>
        <option value="15" selected>Top 15</option>
        <option value="25">Top 25</option>
      </select>
      <span id="scan-status" style="color:var(--text-dim);font-size:13px;"></span>
    </div>
    <div class="panel">
      <div id="scan-results">
        <div class="empty">
          <div class="empty-icon">&#128270;</div>
          <p>Click "Scan Markets" to find trading opportunities</p>
        </div>
      </div>
    </div>
    <div id="analysis-panel"></div>
  </div>

  <!-- POSITIONS -->
  <div id="section-positions" class="section">
    <div class="panel">
      <div class="panel-header">
        <span class="panel-title">All Positions</span>
        <button class="btn btn-outline" onclick="loadPortfolio()">Refresh</button>
      </div>
      <div id="positions-table-full"></div>
    </div>
  </div>

  <!-- HISTORY -->
  <div id="section-history" class="section">
    <div class="panel">
      <div class="panel-header">
        <span class="panel-title">Trade History</span>
        <button class="btn btn-outline" onclick="loadHistory()">Refresh</button>
      </div>
      <div id="history-table"></div>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
// ── State ──
let portfolioData = null;
let scanResults = [];

// ── Navigation ──
function showSection(name) {
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('section-' + name).classList.add('active');
  event.target.classList.add('active');

  if (name === 'overview' || name === 'positions') loadPortfolio();
  if (name === 'history') loadHistory();
}

// ── Portfolio ──
async function loadPortfolio() {
  try {
    const resp = await fetch('/api/portfolio');
    const data = await resp.json();
    portfolioData = data;
    renderPortfolio(data);
  } catch (e) {
    showToast('Failed to load portfolio: ' + e.message, 'error');
  }
}

function renderPortfolio(data) {
  const p = data.portfolio;
  const bankroll = data.config.initial_bankroll;
  const cash = p.cash || 0;
  const pnl = p.total_pnl || 0;
  const invested = bankroll - cash;
  const totalValue = cash + invested + pnl;
  const returnPct = ((totalValue - bankroll) / bankroll * 100).toFixed(1);

  document.getElementById('portfolio-cards').innerHTML = `
    <div class="card">
      <div class="card-label">Total Value</div>
      <div class="card-value">$${totalValue.toFixed(2)}</div>
      <div class="card-sub ${pnl >= 0 ? 'positive' : 'negative'}">${pnl >= 0 ? '+' : ''}${returnPct}% return</div>
    </div>
    <div class="card">
      <div class="card-label">Cash Available</div>
      <div class="card-value">$${cash.toFixed(2)}</div>
      <div class="card-sub" style="color:var(--text-dim)">of $${bankroll.toFixed(2)} bankroll</div>
    </div>
    <div class="card">
      <div class="card-label">Unrealized P&L</div>
      <div class="card-value ${pnl >= 0 ? 'positive' : 'negative'}">${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}</div>
    </div>
    <div class="card">
      <div class="card-label">Trades Today</div>
      <div class="card-value">${p.trades_today || 0}</div>
      <div class="card-sub" style="color:var(--text-dim)">max ${data.config.max_daily_trades}/day</div>
    </div>
  `;

  const posHtml = renderPositionsTable(data.positions || []);
  document.getElementById('positions-table-overview').innerHTML = posHtml;
  document.getElementById('positions-table-full').innerHTML = posHtml;
}

function renderPositionsTable(positions) {
  if (!positions.length) {
    return '<div class="empty"><div class="empty-icon">&#128230;</div><p>No open positions</p></div>';
  }
  let html = '<table><tr><th>Market</th><th>Side</th><th>Shares</th><th>Avg Price</th><th>Current</th><th>P&L</th></tr>';
  for (const p of positions) {
    const pnl = p.unrealized_pnl || 0;
    const cls = pnl >= 0 ? 'positive' : 'negative';
    const sideClass = p.side === 'YES' ? 'badge-green' : 'badge-red';
    html += `<tr>
      <td>${(p.question || p.condition_id).substring(0, 55)}</td>
      <td><span class="badge ${sideClass}">${p.side}</span></td>
      <td>${p.shares.toFixed(2)}</td>
      <td>$${p.avg_price.toFixed(3)}</td>
      <td>$${(p.current_price || 0).toFixed(3)}</td>
      <td class="${cls}">${pnl >= 0 ? '+' : ''}$${pnl.toFixed(4)}</td>
    </tr>`;
  }
  return html + '</table>';
}

// ── Scan ──
async function runScan() {
  const btn = document.getElementById('scan-btn');
  const status = document.getElementById('scan-status');
  const limit = document.getElementById('scan-limit').value;

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Scanning...';
  status.textContent = 'Fetching markets and running AI analysis...';

  document.getElementById('scan-results').innerHTML = '<div class="empty"><span class="spinner"></span> Scanning markets with AI analysis...</div>';

  try {
    const resp = await fetch('/api/scan?limit=' + limit);
    const data = await resp.json();

    if (data.error) {
      document.getElementById('scan-results').innerHTML = `<div class="empty"><p style="color:var(--red)">${data.error}</p></div>`;
      return;
    }

    scanResults = data.results || [];
    status.textContent = `Scanned ${data.total_scanned} markets, showing top ${scanResults.length}`;
    renderScanResults(scanResults);
  } catch (e) {
    document.getElementById('scan-results').innerHTML = `<div class="empty"><p style="color:var(--red)">Error: ${e.message}</p></div>`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = 'Scan Markets';
  }
}

function renderScanResults(results) {
  if (!results.length) {
    document.getElementById('scan-results').innerHTML = '<div class="empty"><p>No results</p></div>';
    return;
  }

  let html = `<table><tr>
    <th>#</th><th>Market</th><th>Category</th><th>YES Price</th><th>AI Prob</th><th>Edge</th><th>Signal</th><th>Actions</th>
  </tr>`;

  results.forEach((r, i) => {
    const m = r.market;
    const a = r.analysis;
    const s = r.signal;
    const edge = a.edge || 0;
    const edgePct = (edge * 100).toFixed(1);
    const absEdge = Math.abs(edge);

    let edgeClass = 'color:var(--text-dim)';
    let barColor = 'var(--text-dim)';
    if (absEdge >= 0.08) { edgeClass = 'color:var(--green)'; barColor = 'var(--green)'; }
    else if (absEdge >= 0.05) { edgeClass = 'color:var(--yellow)'; barColor = 'var(--yellow)'; }

    const barWidth = Math.min(absEdge * 400, 80);

    let signalHtml = '<span style="color:var(--text-dim)">-</span>';
    if (s) {
      const sigClass = s.strength === 'HIGH' ? 'badge-green' : s.strength === 'MEDIUM' ? 'badge-yellow' : 'badge-dim';
      signalHtml = `<span class="badge ${sigClass}">${s.side}</span> <small>$${s.size.toFixed(2)}</small>`;
    }

    const catBadge = {crypto:'badge-yellow', politics:'badge-blue', economics:'badge-green', tech:'badge-blue', sports:'badge-red'}[m.category] || 'badge-dim';

    html += `<tr>
      <td>${i+1}</td>
      <td style="max-width:320px">${m.question.substring(0, 65)}</td>
      <td><span class="badge ${catBadge}">${m.category || '?'}</span></td>
      <td>$${(m.yes_price||0).toFixed(3)}</td>
      <td>${((a.ai_probability||0)*100).toFixed(0)}%</td>
      <td style="${edgeClass};font-weight:600">${edge > 0 ? '+' : ''}${edgePct}%
        <span class="edge-bar" style="background:${barColor};width:${barWidth}px"></span>
      </td>
      <td>${signalHtml}</td>
      <td>
        <button class="btn btn-outline" style="padding:4px 10px;font-size:12px" onclick="deepAnalyze('${m.condition_id}')">Analyze</button>
        ${s ? `<button class="btn btn-success" style="padding:4px 10px;font-size:12px;margin-left:4px" onclick="paperTrade('${m.condition_id}')">Trade</button>` : ''}
      </td>
    </tr>`;
  });

  document.getElementById('scan-results').innerHTML = html + '</table>';
}

// ── Deep Analysis ──
async function deepAnalyze(conditionId) {
  const panel = document.getElementById('analysis-panel');
  panel.innerHTML = '<div class="panel" style="padding:24px"><span class="spinner"></span> Running deep analysis with Claude Sonnet...</div>';
  panel.scrollIntoView({ behavior: 'smooth' });

  try {
    const resp = await fetch('/api/analyze?id=' + encodeURIComponent(conditionId));
    const data = await resp.json();
    if (data.error) {
      panel.innerHTML = `<div class="panel" style="padding:24px;color:var(--red)">${data.error}</div>`;
      return;
    }
    renderDeepAnalysis(panel, data);
  } catch (e) {
    panel.innerHTML = `<div class="panel" style="padding:24px;color:var(--red)">Error: ${e.message}</div>`;
  }
}

function renderDeepAnalysis(panel, data) {
  const m = data.market;
  const a = data.analysis;
  const s = data.signal;
  const edge = a.edge || 0;

  let signalHtml = '';
  if (s) {
    signalHtml = `<div style="margin-top:16px;padding:16px;background:rgba(0,210,160,0.1);border-radius:8px;border:1px solid var(--green)">
      <strong>Signal: ${s.side}</strong> | Edge: ${(s.edge*100).toFixed(1)}% | Size: $${s.size.toFixed(2)} | Strength: ${s.strength}
      <button class="btn btn-success" style="margin-left:12px;padding:6px 16px" onclick="paperTrade('${m.condition_id}')">Execute Paper Trade</button>
    </div>`;
  }

  panel.innerHTML = `<div class="panel" style="padding:24px">
    <h2 style="font-size:18px;margin-bottom:16px">${m.question}</h2>
    <div class="cards" style="grid-template-columns:repeat(4,1fr);margin-bottom:16px">
      <div class="card"><div class="card-label">Market YES</div><div class="card-value">$${(m.yes_price||0).toFixed(3)}</div></div>
      <div class="card"><div class="card-label">AI Probability</div><div class="card-value">${((a.ai_probability||0)*100).toFixed(1)}%</div></div>
      <div class="card"><div class="card-label">Edge</div><div class="card-value ${Math.abs(edge)>=0.08?'positive':''}"">${(edge*100).toFixed(1)}%</div></div>
      <div class="card"><div class="card-label">Confidence</div><div class="card-value">${a.confidence || '?'}/10</div></div>
    </div>
    <div class="analysis-detail">
      ${a.arguments_yes ? `<h3 style="color:var(--green)">Arguments for YES</h3><ul>${a.arguments_yes.map(x=>'<li>'+x+'</li>').join('')}</ul>` : ''}
      ${a.arguments_no ? `<h3 style="color:var(--red)">Arguments for NO</h3><ul>${a.arguments_no.map(x=>'<li>'+x+'</li>').join('')}</ul>` : ''}
      ${a.market_blind_spots ? `<h3 style="color:var(--yellow)">Market Blind Spots</h3><ul>${a.market_blind_spots.map(x=>'<li>'+x+'</li>').join('')}</ul>` : ''}
      <h3>AI Reasoning</h3>
      <p style="font-size:13px;color:var(--text-dim)">${a.reasoning || 'N/A'}</p>
    </div>
    ${signalHtml}
  </div>`;
}

// ── Paper Trade ──
async function paperTrade(conditionId) {
  if (!confirm('Execute paper trade for this market?')) return;

  try {
    const resp = await fetch('/api/trade', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({condition_id: conditionId}),
    });
    const data = await resp.json();
    if (data.error) {
      showToast(data.error, 'error');
      return;
    }
    showToast(`Paper trade executed! ${data.trade.side} $${data.trade.size_usd.toFixed(2)}`, 'success');
    loadPortfolio();
  } catch (e) {
    showToast('Trade failed: ' + e.message, 'error');
  }
}

// ── History ──
async function loadHistory() {
  try {
    const resp = await fetch('/api/history');
    const data = await resp.json();
    renderHistory(data.trades || []);
  } catch (e) {
    showToast('Failed to load history: ' + e.message, 'error');
  }
}

function renderHistory(trades) {
  const el = document.getElementById('history-table');
  if (!trades.length) {
    el.innerHTML = '<div class="empty"><div class="empty-icon">&#128200;</div><p>No trades yet. Start scanning!</p></div>';
    return;
  }
  let html = '<table><tr><th>Time</th><th>Market</th><th>Side</th><th>Price</th><th>Size</th><th>Edge</th><th>Status</th></tr>';
  for (const t of trades) {
    const sideClass = t.side.includes('YES') ? 'badge-green' : 'badge-red';
    html += `<tr>
      <td style="white-space:nowrap">${(t.timestamp||'').substring(0,16)}</td>
      <td>${(t.question || t.condition_id).substring(0, 50)}</td>
      <td><span class="badge ${sideClass}">${t.side}</span></td>
      <td>$${t.price.toFixed(3)}</td>
      <td>$${t.size_usd.toFixed(2)}</td>
      <td>${t.edge ? (t.edge * 100).toFixed(1) + '%' : '-'}</td>
      <td><span class="badge badge-blue">${t.status}</span></td>
    </tr>`;
  }
  el.innerHTML = html + '</table>';
}

// ── Toast ──
function showToast(msg, type = 'success') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast toast-' + type + ' show';
  setTimeout(() => el.classList.remove('show'), 3500);
}

// ── Clock ──
function updateClock() {
  document.getElementById('clock').textContent = new Date().toLocaleTimeString();
}
setInterval(updateClock, 1000);
updateClock();

// ── Init ──
loadPortfolio();
</script>
</body>
</html>
"""
