"""Smoke test for the pivot / trend / support / signal pipeline.

Builds a clean synthetic HH+HL uptrend that pulls back to the latest higher low
on the final bar, verifies that each stage of the pipeline does the right thing.

Run:
    python -m tests.test_pipeline
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.indicators import atr, ema
from src.pivots import filter_alternating, find_pivots
from src.signal import detect_buy_signal
from src.support import higher_low_support
from src.trend import detect_trend


def make_synthetic_uptrend() -> pd.DataFrame:
    """Clean HH+HL uptrend: PL1 -> PH1 -> PL2 (>PL1) -> PH2 (>PH1) -> PL3 (>PL2).

    Last bar touches and bounces off the PL3 support zone with a bullish close.
    """
    # (index, price) anchor points — triangular wave shape
    anchors = [
        (0, 80.0),
        (30, 95.0),    # PH1
        (60, 85.0),    # PL1
        (90, 108.0),   # PH2 (HH)
        (120, 98.0),   # PL2 (HL)
        (150, 122.0),  # PH3 (HH)
        (180, 112.0),  # PL3 (HL)
        (210, 140.0),  # PH4 (HH)
        (240, 126.0),  # PL4 (HL) — latest support
        (260, 126.5),  # flat into present
    ]
    n_total = 265

    xs = np.array([a[0] for a in anchors])
    ys = np.array([a[1] for a in anchors], dtype=float)
    base = np.interp(np.arange(n_total), xs, ys)

    rng = np.random.default_rng(7)
    # Keep noise small and add tiny intrabar range
    noise = rng.normal(0, 0.3, size=n_total)
    close = base + noise
    open_ = close - rng.normal(0, 0.2, size=n_total)
    high = np.maximum(open_, close) + np.abs(rng.normal(0.3, 0.1, size=n_total))
    low = np.minimum(open_, close) - np.abs(rng.normal(0.3, 0.1, size=n_total))
    volume = rng.integers(5_000_000, 15_000_000, size=n_total)

    # Stamp the last bar to clearly enter the support zone and close bullish
    low[-1] = 124.8
    open_[-1] = 125.5
    close[-1] = 127.0
    high[-1] = 127.5

    dates = pd.bdate_range(end="2026-04-20", periods=n_total).strftime("%Y-%m-%d")
    return pd.DataFrame({
        "date": dates,
        "open": open_, "high": high, "low": low, "close": close,
        "volume": volume, "vwap": close,
    })


def main():
    df = make_synthetic_uptrend()
    df["ema_fast"] = ema(df["close"], 50)
    df["ema_slow"] = ema(df["close"], 200)
    df["atr"] = atr(df, 14)

    # Raw pivots
    pivot_highs, pivot_lows = find_pivots(df, k=5)
    print(f"Raw pivot highs: {[(i, round(p, 2)) for i, p in pivot_highs]}")
    print(f"Raw pivot lows:  {[(i, round(p, 2)) for i, p in pivot_lows]}")

    # Alternation filter (merge consecutive same-type)
    pivot_highs, pivot_lows = filter_alternating(pivot_highs, pivot_lows)
    print(f"Filtered highs:  {[(i, round(p, 2)) for i, p in pivot_highs]}")
    print(f"Filtered lows:   {[(i, round(p, 2)) for i, p in pivot_lows]}")

    trend = detect_trend(pivot_highs, pivot_lows)
    print(f"Trend: {trend}")
    assert trend["trend_valid"], f"expected valid uptrend, got {trend}"

    last_atr = float(df.iloc[-1]["atr"])
    zone = higher_low_support(df, pivot_lows, last_atr, buffer_mult=0.5)
    print(f"Support zone: {zone}")
    assert zone is not None, "expected higher_low support"
    assert zone.support_type == "higher_low"

    sig = detect_buy_signal(df, zone)
    print(f"Signal: {sig}")
    assert sig["triggered"], f"expected buy signal trigger on last bar, got {sig}"

    print("\n[OK] synthetic pipeline test passed.")


if __name__ == "__main__":
    main()
