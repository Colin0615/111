"""SQLite database for storing markets, analyses, trades, and portfolio state."""

from __future__ import annotations

import aiosqlite
import json
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

from src.core.config import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS markets (
    condition_id TEXT PRIMARY KEY,
    question     TEXT NOT NULL,
    description  TEXT,
    category     TEXT,
    end_date     TEXT,
    yes_price    REAL,
    no_price     REAL,
    volume_24h   REAL DEFAULT 0,
    liquidity    REAL DEFAULT 0,
    active       INTEGER DEFAULT 1,
    updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS analyses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id    TEXT NOT NULL,
    timestamp       TEXT NOT NULL,
    model           TEXT NOT NULL,
    ai_probability  REAL NOT NULL,
    confidence      REAL NOT NULL,
    market_price    REAL NOT NULL,
    edge            REAL NOT NULL,
    reasoning       TEXT,
    recommendation  TEXT,
    news_context    TEXT,
    FOREIGN KEY (condition_id) REFERENCES markets(condition_id)
);

CREATE TABLE IF NOT EXISTS trades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id  TEXT NOT NULL,
    timestamp     TEXT NOT NULL,
    side          TEXT NOT NULL,          -- BUY_YES, BUY_NO, SELL_YES, SELL_NO
    price         REAL NOT NULL,
    size_usd      REAL NOT NULL,
    shares        REAL NOT NULL,
    ai_probability REAL,
    edge          REAL,
    status        TEXT DEFAULT 'PAPER',   -- PAPER, PENDING, FILLED, CANCELLED, FAILED
    order_id      TEXT,
    pnl           REAL,
    notes         TEXT,
    FOREIGN KEY (condition_id) REFERENCES markets(condition_id)
);

CREATE TABLE IF NOT EXISTS portfolio (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    bankroll      REAL NOT NULL,
    cash          REAL NOT NULL,
    total_pnl     REAL DEFAULT 0,
    trades_today  INTEGER DEFAULT 0,
    last_trade_date TEXT,
    updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS positions (
    condition_id  TEXT PRIMARY KEY,
    side          TEXT NOT NULL,         -- YES or NO
    shares        REAL NOT NULL,
    avg_price     REAL NOT NULL,
    current_price REAL,
    unrealized_pnl REAL DEFAULT 0,
    FOREIGN KEY (condition_id) REFERENCES markets(condition_id)
);

CREATE TABLE IF NOT EXISTS news_cache (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    source     TEXT NOT NULL,
    title      TEXT NOT NULL,
    url        TEXT UNIQUE,
    content    TEXT,
    published  TEXT,
    fetched_at TEXT NOT NULL
);
"""


async def get_db() -> aiosqlite.Connection:
    Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(config.db_path)
    db.row_factory = aiosqlite.Row
    await db.executescript(_SCHEMA)
    return db


async def init_portfolio(bankroll: float) -> None:
    db = await get_db()
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """INSERT OR IGNORE INTO portfolio (id, bankroll, cash, total_pnl, trades_today, updated_at)
           VALUES (1, ?, ?, 0, 0, ?)""",
        (bankroll, bankroll, now),
    )
    await db.commit()
    await db.close()


async def get_portfolio() -> dict:
    db = await get_db()
    row = await db.execute_fetchall("SELECT * FROM portfolio WHERE id = 1")
    await db.close()
    if not row:
        return {}
    r = row[0]
    return {
        "bankroll": r["bankroll"],
        "cash": r["cash"],
        "total_pnl": r["total_pnl"],
        "trades_today": r["trades_today"],
        "last_trade_date": r["last_trade_date"],
    }


async def save_market(market: dict) -> None:
    db = await get_db()
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """INSERT OR REPLACE INTO markets
           (condition_id, question, description, category, end_date,
            yes_price, no_price, volume_24h, liquidity, active, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            market["condition_id"],
            market["question"],
            market.get("description", ""),
            market.get("category", ""),
            market.get("end_date", ""),
            market.get("yes_price", 0),
            market.get("no_price", 0),
            market.get("volume_24h", 0),
            market.get("liquidity", 0),
            1,
            now,
        ),
    )
    await db.commit()
    await db.close()


async def save_analysis(analysis: dict) -> int:
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO analyses
           (condition_id, timestamp, model, ai_probability, confidence,
            market_price, edge, reasoning, recommendation, news_context)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            analysis["condition_id"],
            analysis["timestamp"],
            analysis["model"],
            analysis["ai_probability"],
            analysis["confidence"],
            analysis["market_price"],
            analysis["edge"],
            analysis.get("reasoning", ""),
            analysis.get("recommendation", ""),
            analysis.get("news_context", ""),
        ),
    )
    await db.commit()
    row_id = cursor.lastrowid
    await db.close()
    return row_id


async def save_trade(trade: dict) -> int:
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO trades
           (condition_id, timestamp, side, price, size_usd, shares,
            ai_probability, edge, status, order_id, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            trade["condition_id"],
            trade["timestamp"],
            trade["side"],
            trade["price"],
            trade["size_usd"],
            trade["shares"],
            trade.get("ai_probability"),
            trade.get("edge"),
            trade.get("status", "PAPER"),
            trade.get("order_id"),
            trade.get("notes", ""),
        ),
    )
    # Update portfolio
    await db.execute(
        """UPDATE portfolio SET
           cash = cash - ?,
           trades_today = trades_today + 1,
           last_trade_date = ?,
           updated_at = ?
           WHERE id = 1""",
        (trade["size_usd"], trade["timestamp"][:10], trade["timestamp"]),
    )
    await db.commit()
    row_id = cursor.lastrowid
    await db.close()
    return row_id


async def get_active_markets() -> list[dict]:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM markets WHERE active = 1 ORDER BY volume_24h DESC"
    )
    await db.close()
    return [dict(r) for r in rows]


async def get_recent_analyses(condition_id: str, limit: int = 5) -> list[dict]:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM analyses WHERE condition_id = ? ORDER BY timestamp DESC LIMIT ?",
        (condition_id, limit),
    )
    await db.close()
    return [dict(r) for r in rows]


async def get_open_positions() -> list[dict]:
    db = await get_db()
    rows = await db.execute_fetchall(
        """SELECT p.*, m.question, m.yes_price, m.no_price
           FROM positions p JOIN markets m ON p.condition_id = m.condition_id"""
    )
    await db.close()
    return [dict(r) for r in rows]


async def get_trade_history(limit: int = 50) -> list[dict]:
    db = await get_db()
    rows = await db.execute_fetchall(
        """SELECT t.*, m.question FROM trades t
           JOIN markets m ON t.condition_id = m.condition_id
           ORDER BY t.timestamp DESC LIMIT ?""",
        (limit,),
    )
    await db.close()
    return [dict(r) for r in rows]
