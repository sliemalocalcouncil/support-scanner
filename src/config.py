"""Central configuration for the scanner.

All strategy parameters and paths live here. Override via env vars where needed.
"""
from dataclasses import dataclass
import os


@dataclass
class Config:
    # --- Polygon API ---
    polygon_api_key: str = os.getenv("POLYGON_API_KEY", "")
    # Starter plan is typically 5 req/min. Override via env if your plan differs.
    polygon_rate_limit_per_min: int = int(os.getenv("POLYGON_RATE_LIMIT_PER_MIN", "5"))

    # --- Timeframe / Lookback ---
    timeframe: str = "1d"
    lookback_bars: int = 250           # bars used per ticker for analysis
    cache_lookback_days: int = 330     # calendar days kept in bar cache

    # --- Pivot / Trend ---
    pivot_window: int = 4              # k: ±k bars around a pivot candidate
    min_swing_atr_mult: float = 1.5    # minimum swing amplitude in ATR multiples
    ema_fast: int = 50
    ema_slow: int = 200
    atr_period: int = 14

    # --- Support ---
    support_buffer_atr_mult: float = 0.25

    # --- Liquidity / Price filters ---
    min_avg_dollar_volume: float = 10_000_000.0   # $10M
    min_price: float = 5.0

    # --- Signal ---
    min_signal_score: float = 60.0

    # --- Paths ---
    # User-managed plain-text ticker list at the repo root. Edit by hand
    # (or via GitHub's web UI) to change the universe.
    tickers_file: str = os.getenv("TICKERS_FILE", "ticker.txt")
    bars_cache: str = "data/bars.csv"
    watchlist_path: str = "state/watchlist.json"
    scan_meta_path: str = "state/last_scan_meta.json"
    out_dir: str = "out"

    # --- Safety ---
    # Max number of missing dates fetched per run (caps initial bootstrap).
    max_fetch_per_run: int = int(os.getenv("MAX_FETCH_PER_RUN", "400"))

    # --- Telegram notifications (optional) ---
    # If both are empty the notifier is a silent no-op.
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    # Send a "no signals today" message on empty scans. Off by default to
    # avoid spam on quiet days.
    telegram_notify_on_empty: bool = os.getenv("TELEGRAM_NOTIFY_ON_EMPTY", "0").strip().lower() in ("1", "true", "yes", "on")
    # Cap the number of signals shown per message.
    telegram_max_signals: int = int(os.getenv("TELEGRAM_MAX_SIGNALS", "30"))


CFG = Config()
