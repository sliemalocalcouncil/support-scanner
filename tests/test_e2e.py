"""End-to-end smoke test for the scanner CLIs.

Seeds `data/bars.csv` with synthetic OHLCV for a handful of fake tickers,
then runs `scan_universe --skip-fetch` and `scan_signals` to verify the
full pipeline produces a watchlist and a signals CSV.

Run:
    python -m tests.test_e2e
"""
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_pipeline import make_synthetic_uptrend


def make_downtrend(n_bars: int = 265) -> pd.DataFrame:
    """Clear LH + LL downtrend — should NOT produce a valid uptrend."""
    anchors = [
        (0, 200.0),
        (30, 180.0), (60, 190.0),   # LH vs 200
        (90, 160.0), (120, 170.0),  # LH
        (150, 140.0), (180, 150.0), # LH
        (210, 120.0), (240, 125.0), # LH
        (260, 118.0),
    ]
    xs = np.array([a[0] for a in anchors])
    ys = np.array([a[1] for a in anchors], dtype=float)
    base = np.interp(np.arange(n_bars), xs, ys)

    rng = np.random.default_rng(99)
    noise = rng.normal(0, 0.4, size=n_bars)
    close = base + noise
    open_ = close - rng.normal(0, 0.3, size=n_bars)
    high = np.maximum(open_, close) + np.abs(rng.normal(0.4, 0.15, size=n_bars))
    low = np.minimum(open_, close) - np.abs(rng.normal(0.4, 0.15, size=n_bars))
    volume = rng.integers(5_000_000, 15_000_000, size=n_bars)
    dates = pd.bdate_range(end="2026-04-20", periods=n_bars).strftime("%Y-%m-%d")
    return pd.DataFrame({
        "date": dates,
        "open": open_, "high": high, "low": low, "close": close,
        "volume": volume, "vwap": close,
    })


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(root)

    # Seed a test-only ticker file + bars.csv with synthetic data.
    # We write to test_ticker.txt and tell scan_universe to read from it
    # via TICKERS_FILE env, so we don't clobber the real ticker.txt.
    os.makedirs("data", exist_ok=True)
    test_tickers_path = "test_ticker.txt"
    with open(test_tickers_path, "w") as f:
        f.write("# test tickers\nFAKE1\nFAKE2\nFAKE3\n")

    uptrend = make_synthetic_uptrend()
    downtrend = make_downtrend()

    all_bars = []
    for ticker, df in [("FAKE1", uptrend), ("FAKE2", uptrend), ("FAKE3", downtrend)]:
        copy = df.copy()
        copy.insert(0, "ticker", ticker)
        all_bars.append(copy[["ticker", "date", "open", "high", "low", "close", "volume", "vwap"]])

    bars = pd.concat(all_bars, ignore_index=True)
    bars.to_csv("data/bars.csv", index=False)
    print(f"Seeded {len(bars)} bars across {bars['ticker'].nunique()} tickers")

    # Clean outputs
    for p in ("state/watchlist.json", "out/signals_latest.csv"):
        if os.path.exists(p):
            os.remove(p)

    # Run universe scan (skip fetch — using seeded cache + test ticker file)
    test_env = {**os.environ, "TICKERS_FILE": test_tickers_path}
    print("\n--- scan_universe --skip-fetch ---")
    r = subprocess.run(
        [sys.executable, "-m", "src.scan_universe", "--skip-fetch"],
        capture_output=True, text=True, env=test_env,
    )
    print(r.stdout)
    if r.returncode != 0:
        print("STDERR:", r.stderr)
        sys.exit(1)

    # Verify watchlist contains uptrend tickers but not sideways
    with open("state/watchlist.json") as f:
        wl = json.load(f)
    primary_tickers = {item["ticker"] for item in wl["primary"]}
    monitor_tickers = {item["ticker"] for item in wl["monitor"]}
    all_watchlist = primary_tickers | monitor_tickers
    print(f"Primary watchlist: {primary_tickers}")
    print(f"Monitor watchlist: {monitor_tickers}")

    assert "FAKE1" in primary_tickers or "FAKE1" in all_watchlist, \
        "expected uptrend ticker FAKE1 on watchlist"
    assert "FAKE3" not in primary_tickers, \
        "sideways ticker FAKE3 should NOT be on primary watchlist"

    # Run signal scan WITH DEFAULT min_score (no --min-score override).
    # This is the exact gap flagged in code review: the previous E2E
    # ran with --min-score 0 which could mask scoring misconfiguration.
    # Now that scoring is fixed, a strong valid signal MUST clear the
    # default threshold.
    print("\n--- scan_signals (DEFAULT min_score) ---")
    r = subprocess.run(
        [sys.executable, "-m", "src.scan_signals"],
        capture_output=True, text=True,
    )
    print(r.stdout)
    if r.returncode != 0:
        print("STDERR:", r.stderr)
        sys.exit(1)

    # Check the signals CSV exists and has at least one row
    assert os.path.exists("out/signals_latest.csv"), "signals_latest.csv not written"
    sig_df = pd.read_csv("out/signals_latest.csv")
    print(f"Signals CSV: {len(sig_df)} rows, columns: {list(sig_df.columns)}")
    assert len(sig_df) >= 1, "expected at least one signal row from uptrend fakes"

    # Clean up the test-only ticker file
    try:
        os.remove(test_tickers_path)
    except OSError:
        pass

    print("\n[OK] end-to-end test passed.")


if __name__ == "__main__":
    main()
