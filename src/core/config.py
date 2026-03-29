"""Central configuration loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv

# Load .env from project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _env_float(key: str, default: float = 0.0) -> float:
    return float(os.getenv(key, str(default)))


def _env_int(key: str, default: int = 0) -> int:
    return int(os.getenv(key, str(default)))


@dataclass(frozen=True)
class PolymarketConfig:
    private_key: str = field(default_factory=lambda: _env("POLYMARKET_PRIVATE_KEY"))
    api_key: str = field(default_factory=lambda: _env("POLYMARKET_API_KEY"))
    api_secret: str = field(default_factory=lambda: _env("POLYMARKET_API_SECRET"))
    api_passphrase: str = field(default_factory=lambda: _env("POLYMARKET_API_PASSPHRASE"))
    clob_url: str = "https://clob.polymarket.com"
    gamma_url: str = "https://gamma-api.polymarket.com"
    chain_id: int = 137  # Polygon mainnet


@dataclass(frozen=True)
class AIConfig:
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    fast_model: str = "claude-haiku-4-5-20251001"
    strong_model: str = "claude-sonnet-4-6"
    max_tokens: int = 1024


@dataclass(frozen=True)
class TradingConfig:
    initial_bankroll: float = field(default_factory=lambda: _env_float("INITIAL_BANKROLL", 50.0))
    max_position_size: float = field(default_factory=lambda: _env_float("MAX_POSITION_SIZE", 5.0))
    min_edge_threshold: float = field(default_factory=lambda: _env_float("MIN_EDGE_THRESHOLD", 0.08))
    max_daily_trades: int = field(default_factory=lambda: _env_int("MAX_DAILY_TRADES", 3))
    stop_loss_pct: float = field(default_factory=lambda: _env_float("STOP_LOSS_PCT", 0.20))
    kelly_fraction: float = field(default_factory=lambda: _env_float("KELLY_FRACTION", 0.15))
    min_liquidity_usd: float = 500.0  # Skip markets with < $500 daily volume
    min_hours_to_expiry: float = 24.0  # Skip markets expiring within 24h


@dataclass(frozen=True)
class NewsConfig:
    newsapi_key: str = field(default_factory=lambda: _env("NEWSAPI_KEY"))


@dataclass(frozen=True)
class NotificationConfig:
    telegram_bot_token: str = field(default_factory=lambda: _env("TELEGRAM_BOT_TOKEN"))
    telegram_chat_id: str = field(default_factory=lambda: _env("TELEGRAM_CHAT_ID"))


@dataclass(frozen=True)
class Config:
    polymarket: PolymarketConfig = field(default_factory=PolymarketConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    news: NewsConfig = field(default_factory=NewsConfig)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    db_path: str = field(default_factory=lambda: str(_PROJECT_ROOT / "data" / "trader.db"))


# Singleton
config = Config()
