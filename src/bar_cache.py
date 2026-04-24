"""Local OHLCV bar cache.

Stored as a single CSV for simplicity. Fine for ~150k rows (500 tickers × 300 days).
Incremental-update friendly: we detect which business dates are missing and
fetch only those via Grouped Daily (1 API call per missing date).
"""
import os
from datetime import datetime, timedelta
from typing import List, Set

import pandas as pd


COLUMNS = ["ticker", "date", "open", "high", "low", "close", "volume", "vwap"]


def load_cache(path: str) -> pd.DataFrame:
    if os.path.exists(path) and os.path.getsize(path) > 0:
        df = pd.read_csv(path, dtype={"ticker": str})
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        return df
    return pd.DataFrame(columns=COLUMNS)


def save_cache(df: pd.DataFrame, path: str, lookback_days: int = 330) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if df.empty:
        df.to_csv(path, index=False)
        return

    cutoff = (datetime.utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    df = df[df["date"] >= cutoff].copy()
    df = df.sort_values(["ticker", "date"]).drop_duplicates(["ticker", "date"], keep="last")
    df.to_csv(path, index=False)


def get_ticker_bars(df: pd.DataFrame, ticker: str, n_bars: int = 0) -> pd.DataFrame:
    """Return a single ticker's bars in ascending date order."""
    if df.empty:
        return df
    sub = df[df["ticker"] == ticker].sort_values("date").reset_index(drop=True)
    if n_bars and len(sub) > n_bars:
        sub = sub.tail(n_bars).reset_index(drop=True)
    return sub


def missing_business_dates(df: pd.DataFrame, end_date: str, lookback_days: int) -> List[str]:
    """Return business dates in [end_date - lookback_days, end_date] that are NOT in cache.

    Ordered ascending (oldest first) so initial bootstrap fills from the past forward.
    """
    end = pd.to_datetime(end_date)
    start = end - pd.Timedelta(days=lookback_days)
    business_days = pd.bdate_range(start=start, end=end).strftime("%Y-%m-%d").tolist()

    existing: Set[str] = set()
    if not df.empty:
        existing = set(df["date"].unique().tolist())

    return [d for d in business_days if d not in existing]
