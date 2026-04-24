"""Polygon REST API client.

Uses the Grouped Daily Aggregates endpoint to fetch one call = all US stocks for a day.
This is the efficient path for scanning the full S&P 500 universe on the Starter plan.
"""
import time
from typing import Optional

import pandas as pd
import requests


class PolygonClient:
    BASE_URL = "https://api.polygon.io"

    def __init__(self, api_key: str, rate_limit_per_min: int = 5):
        if not api_key:
            raise ValueError("Polygon API key is required")
        self.api_key = api_key
        self.min_interval = 60.0 / max(1, rate_limit_per_min)
        self._last_request_time = 0.0

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request_time
        wait = self.min_interval - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_time = time.time()

    def _request(self, path: str, params: Optional[dict] = None, max_retries: int = 4) -> dict:
        url = f"{self.BASE_URL}{path}"
        params = dict(params or {})
        params["apiKey"] = self.api_key

        last_err = None
        for attempt in range(max_retries):
            self._throttle()
            try:
                resp = requests.get(url, params=params, timeout=30)
                if resp.status_code == 429:
                    wait = min(60, 2 ** attempt * 5)
                    print(f"    [polygon] 429 rate limited, sleeping {wait}s")
                    time.sleep(wait)
                    continue
                if resp.status_code == 403:
                    # Likely plan restriction — let caller handle.
                    raise PermissionError(f"403 Forbidden: {resp.text[:200]}")
                resp.raise_for_status()
                return resp.json()
            except (requests.RequestException, PermissionError) as e:
                last_err = e
                if isinstance(e, PermissionError):
                    raise
                wait = 2 ** attempt
                print(f"    [polygon] request failed ({e}), retry in {wait}s")
                time.sleep(wait)
        raise RuntimeError(f"Polygon request failed after {max_retries} attempts: {last_err}")

    def grouped_daily(self, date: str) -> pd.DataFrame:
        """Fetch all US stock daily bars for `date` (YYYY-MM-DD).

        Returns columns: ticker, date, open, high, low, close, volume, vwap.
        Empty DataFrame on weekends/holidays.
        """
        path = f"/v2/aggs/grouped/locale/us/market/stocks/{date}"
        data = self._request(path, params={"adjusted": "true"})

        if data.get("status") not in ("OK", "DELAYED"):
            return _empty_bars_df()

        results = data.get("results") or []
        if not results:
            return _empty_bars_df()

        df = pd.DataFrame(results)
        df = df.rename(columns={
            "T": "ticker", "o": "open", "h": "high", "l": "low",
            "c": "close", "v": "volume", "vw": "vwap",
        })
        df["date"] = date
        # Some tickers have no vwap — fill with close.
        if "vwap" not in df.columns:
            df["vwap"] = df["close"]
        else:
            df["vwap"] = df["vwap"].fillna(df["close"])
        return df[["ticker", "date", "open", "high", "low", "close", "volume", "vwap"]].copy()

    def ticker_aggs(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        """Per-ticker daily aggregates (fallback)."""
        path = f"/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}"
        data = self._request(path, params={"adjusted": "true", "sort": "asc", "limit": 50000})
        results = data.get("results") or []
        if not results:
            return _empty_bars_df()
        df = pd.DataFrame(results)
        df = df.rename(columns={
            "o": "open", "h": "high", "l": "low", "c": "close",
            "v": "volume", "vw": "vwap", "t": "timestamp",
        })
        df["ticker"] = ticker
        df["date"] = pd.to_datetime(df["timestamp"], unit="ms").dt.strftime("%Y-%m-%d")
        if "vwap" not in df.columns:
            df["vwap"] = df["close"]
        else:
            df["vwap"] = df["vwap"].fillna(df["close"])
        return df[["ticker", "date", "open", "high", "low", "close", "volume", "vwap"]].copy()


def _empty_bars_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["ticker", "date", "open", "high", "low", "close", "volume", "vwap"])
