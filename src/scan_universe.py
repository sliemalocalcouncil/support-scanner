"""Universe Scan.

1. Load the ticker list from `ticker.txt` (user-managed; see README).
2. Incrementally update the bar cache using Polygon's Grouped Daily endpoint
   (1 API call per missing business date).
3. For each ticker, build features and classify:
     - "primary"  = higher-low support in a valid HH+HL uptrend (Type A)
     - "monitor"  = breakout-retest support candidate (Type B, lower priority)
4. Write `state/watchlist.json` + `out/watchlist_<YYYY-MM-DD>.csv`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd

# Make `python -m src.scan_universe` work when invoked from repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.bar_cache import (
    get_ticker_bars,
    load_cache,
    missing_business_dates,
    save_cache,
)
from src.config import CFG
from src.indicators import atr, ema
from src.pivots import filter_alternating, filter_by_swing_amplitude, find_pivots
from src.polygon_client import PolygonClient
from src.support import breakout_retest_support, higher_low_support
from src.trend import detect_trend
from src.universe_loader import load_sp500_tickers


def analyze_ticker(ticker: str, bars: pd.DataFrame) -> Optional[Dict]:
    """Return a watchlist entry if the ticker qualifies, else None."""
    if len(bars) < max(CFG.ema_slow + 5, CFG.lookback_bars // 2):
        return None

    bars = bars.copy()
    bars["ema_fast"] = ema(bars["close"], CFG.ema_fast)
    bars["ema_slow"] = ema(bars["close"], CFG.ema_slow)
    bars["atr"] = atr(bars, CFG.atr_period)

    last = bars.iloc[-1]
    last_close = float(last["close"])
    last_atr = float(last["atr"])
    ema_fast_val = float(last["ema_fast"])
    ema_slow_val = float(last["ema_slow"])

    # Liquidity + price filters
    avg_dv = float((bars["close"] * bars["volume"]).tail(20).mean())
    if avg_dv < CFG.min_avg_dollar_volume:
        return None
    if last_close < CFG.min_price:
        return None

    # EMA structure filter.
    # Note: we deliberately do NOT require `close > ema_fast` because a
    # support-retest pullback often dips temporarily below EMA50 — that's
    # the whole setup. We require trend structure (ema_fast > ema_slow) and
    # that close is above the long-term EMA (ema_slow).
    if not (last_close > ema_slow_val and ema_fast_val > ema_slow_val):
        return None

    pivot_highs, pivot_lows = find_pivots(bars, k=CFG.pivot_window)
    pivot_highs, pivot_lows = filter_alternating(pivot_highs, pivot_lows)
    pivot_highs, pivot_lows = filter_by_swing_amplitude(
        pivot_highs, pivot_lows, min_swing=last_atr * CFG.min_swing_atr_mult
    )
    trend = detect_trend(pivot_highs, pivot_lows)

    # Try Type A (higher_low) first — requires valid uptrend.
    support = None
    support_category = None
    if trend["trend_valid"]:
        support = higher_low_support(bars, pivot_lows, last_atr, CFG.support_buffer_atr_mult)
        if support is not None:
            support_category = "primary"

    # Fallback to Type B (breakout_retest) — monitored but lower priority.
    if support is None:
        support = breakout_retest_support(
            bars, pivot_highs, last_close, last_atr, CFG.support_buffer_atr_mult
        )
        if support is not None:
            support_category = "monitor"

    if support is None:
        return None

    return {
        "ticker": ticker,
        "last_date": str(last["date"]),
        "last_close": round(last_close, 4),
        "atr14": round(last_atr, 4),
        "ema50": round(ema_fast_val, 4),
        "ema200": round(ema_slow_val, 4),
        "avg_dollar_volume": round(avg_dv, 0),
        "trend": trend["trend"],
        "hh_count": trend["hh_count"],
        "hl_count": trend["hl_count"],
        "last_ph_price": round(trend["last_ph"][1], 4) if trend["last_ph"] else None,
        "last_pl_price": round(trend["last_pl"][1], 4) if trend["last_pl"] else None,
        "support_type": support.support_type,
        "support_category": support_category,
        "support_price": round(support.price, 4),
        "zone_low": round(support.zone_low, 4),
        "zone_high": round(support.zone_high, 4),
        "pivot_date": support.pivot_date,
    }


def update_bar_cache(
    client: PolygonClient,
    cache: pd.DataFrame,
    tickers_set: set,
    max_fetch: int,
) -> pd.DataFrame:
    """Fetch missing business dates via Grouped Daily endpoint."""
    today = datetime.now(timezone.utc).date().strftime("%Y-%m-%d")
    missing = missing_business_dates(cache, today, CFG.cache_lookback_days)

    if not missing:
        print("Bar cache is up to date.")
        return cache

    if len(missing) > max_fetch:
        print(f"Found {len(missing)} missing dates; capping to {max_fetch} this run.")
        missing = missing[-max_fetch:]  # keep most recent
    else:
        print(f"Fetching {len(missing)} missing business dates...")

    new_frames: List[pd.DataFrame] = []
    for date in missing:
        try:
            df = client.grouped_daily(date)
        except PermissionError as e:
            print(f"  {date}: PERMISSION ERROR from Polygon — {e}")
            print("  -> Your plan may not allow Grouped Daily. Aborting fetch.")
            break
        except Exception as e:
            print(f"  {date}: fetch failed ({e})")
            continue

        if df.empty:
            print(f"  {date}: no data (weekend/holiday or not yet available)")
            continue

        df = df[df["ticker"].isin(tickers_set)].copy()
        new_frames.append(df)
        print(f"  {date}: {len(df)} rows")

    if not new_frames:
        return cache

    combined = pd.concat([cache] + new_frames, ignore_index=True)
    combined = combined.sort_values(["ticker", "date"]).drop_duplicates(
        ["ticker", "date"], keep="last"
    )
    return combined


def main():
    parser = argparse.ArgumentParser(description="S&P 500 support buy alert — Universe Scan")
    parser.add_argument("--output-dir", default=CFG.out_dir)
    parser.add_argument("--skip-fetch", action="store_true", help="Skip Polygon fetch; use cache as-is.")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    os.makedirs(os.path.dirname(CFG.watchlist_path), exist_ok=True)

    try:
        tickers = load_sp500_tickers(CFG.tickers_file)
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    if not tickers:
        print(f"ERROR: no tickers loaded from {CFG.tickers_file} (file is empty or all comments).")
        sys.exit(1)
    print(f"Loaded {len(tickers)} tickers from {CFG.tickers_file}")

    cache = load_cache(CFG.bars_cache)
    print(f"Cache has {len(cache)} rows ({cache['ticker'].nunique() if not cache.empty else 0} tickers)")

    if not args.skip_fetch:
        if not CFG.polygon_api_key:
            print("ERROR: POLYGON_API_KEY not set")
            sys.exit(1)
        client = PolygonClient(CFG.polygon_api_key, rate_limit_per_min=CFG.polygon_rate_limit_per_min)
        cache = update_bar_cache(client, cache, set(tickers), max_fetch=CFG.max_fetch_per_run)
        save_cache(cache, CFG.bars_cache, lookback_days=CFG.cache_lookback_days)

    if cache.empty:
        print("ERROR: bar cache is empty; cannot continue.")
        sys.exit(1)

    # Analyze every ticker
    print("\nAnalyzing tickers...")
    results: List[Dict] = []
    failed = 0
    for i, ticker in enumerate(tickers):
        bars = get_ticker_bars(cache, ticker, n_bars=CFG.lookback_bars)
        try:
            entry = analyze_ticker(ticker, bars)
            if entry is not None:
                results.append(entry)
        except Exception as e:
            failed += 1
            print(f"  {ticker}: error ({e})")
        if (i + 1) % 100 == 0:
            print(f"  ...scanned {i + 1}/{len(tickers)} | watchlist so far: {len(results)}")

    primary = [r for r in results if r["support_category"] == "primary"]
    monitor = [r for r in results if r["support_category"] == "monitor"]
    print(f"\nTotal watchlist: {len(results)} (primary={len(primary)}, monitor={len(monitor)}, failed={failed})")

    # Save state
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    watchlist = {
        "updated_at": now,
        "timeframe": CFG.timeframe,
        "primary": primary,
        "monitor": monitor,
    }
    with open(CFG.watchlist_path, "w") as f:
        json.dump(watchlist, f, indent=2, default=str)
    print(f"Saved {CFG.watchlist_path}")

    meta = {
        "scan_type": "universe",
        "finished_at": now,
        "ticker_count": len(tickers),
        "primary_count": len(primary),
        "monitor_count": len(monitor),
        "failed_count": failed,
        "cache_rows": len(cache),
    }
    with open(CFG.scan_meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    # Save watchlist CSV for easy download
    if results:
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        csv_path = os.path.join(args.output_dir, f"watchlist_{today_str}.csv")
        pd.DataFrame(results).to_csv(csv_path, index=False)
        print(f"Saved {csv_path}")


if __name__ == "__main__":
    main()
