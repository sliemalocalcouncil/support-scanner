"""Signal Scan.

Runs after Universe Scan:
  1. Load watchlist.json.
  2. For each watchlist item, read its bars from cache and re-validate the zone
     against the latest bar.
  3. Emit a buy signal row if trigger conditions are met.
  4. Write `out/signals_<YYYY-MM-DD>.csv` (always, even if empty).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.bar_cache import get_ticker_bars, load_cache
from src.config import CFG
from src.indicators import atr, ema
from src.notifier import TelegramNotifier
from src.pivots import filter_alternating, filter_by_swing_amplitude, find_pivots
from src.scoring import compute_score_breakdown
from src.signal import detect_buy_signal
from src.support import SupportZone
from src.trend import detect_trend


SIGNAL_COLUMNS = [
    "signal_date", "ticker", "support_category", "support_type",
    "last_close", "support_price", "zone_low", "zone_high",
    "last_open", "last_high", "last_low",
    "atr14", "ema50", "ema200",
    "hh_count", "hl_count",
    "last_ph_price", "last_pl_price",
    "recent_high_20", "recent_high_252",
    "lower_tail_ratio",
    "score", "score_trend", "score_support_quality",
    "score_reaction", "score_liquidity", "score_room",
    "reasons",
]


def process_item(item: Dict, cache: pd.DataFrame) -> Optional[Dict]:
    ticker = item["ticker"]
    bars = get_ticker_bars(cache, ticker, n_bars=CFG.lookback_bars)
    if len(bars) < max(CFG.ema_slow + 5, CFG.lookback_bars // 2):
        return None

    bars = bars.copy()
    bars["ema_fast"] = ema(bars["close"], CFG.ema_fast)
    bars["ema_slow"] = ema(bars["close"], CFG.ema_slow)
    bars["atr"] = atr(bars, CFG.atr_period)

    last = bars.iloc[-1]
    last_close = float(last["close"])
    last_atr = float(last["atr"])

    # Re-validate trend
    pivot_highs, pivot_lows = find_pivots(bars, k=CFG.pivot_window)
    pivot_highs, pivot_lows = filter_alternating(pivot_highs, pivot_lows)
    pivot_highs, pivot_lows = filter_by_swing_amplitude(
        pivot_highs, pivot_lows, min_swing=last_atr * CFG.min_swing_atr_mult
    )
    trend = detect_trend(pivot_highs, pivot_lows)

    # For primary Type A, trend must still be valid
    if item["support_category"] == "primary" and not trend["trend_valid"]:
        return None

    # Reconstruct zone from watchlist snapshot
    zone = SupportZone(
        support_type=item["support_type"],
        price=float(item["support_price"]),
        zone_low=float(item["zone_low"]),
        zone_high=float(item["zone_high"]),
        pivot_index=0,
        pivot_date=str(item.get("pivot_date", "")),
    )

    # Invalidation: close clearly below zone_low
    if last_close < zone.zone_low - last_atr * 0.1:
        return None

    sig = detect_buy_signal(bars, zone)
    if not sig["triggered"]:
        return None

    avg_dv = float((bars["close"] * bars["volume"]).tail(20).mean())

    # Multi-level resistance inputs for room_to_resistance scoring.
    # Use windows that actually exist in the data — falls back gracefully.
    recent_high_20 = float(bars["high"].tail(20).max()) if len(bars) >= 20 else None
    recent_high_252 = float(bars["high"].tail(252).max()) if len(bars) >= 20 else None

    features = {
        "hh_count": trend["hh_count"],
        "hl_count": trend["hl_count"],
        "last_close": last_close,
        "atr14": last_atr,
        "last_ph_price": trend["last_ph"][1] if trend["last_ph"] else None,
        "recent_high_20": recent_high_20,
        "recent_high_252": recent_high_252,
        "avg_dollar_volume": avg_dv,
    }
    breakdown = compute_score_breakdown(features, zone, sig)

    return {
        "signal_date": str(last["date"]),
        "ticker": ticker,
        "support_category": item["support_category"],
        "support_type": item["support_type"],
        "last_close": round(last_close, 4),
        "support_price": round(zone.price, 4),
        "zone_low": round(zone.zone_low, 4),
        "zone_high": round(zone.zone_high, 4),
        "last_open": round(float(last["open"]), 4),
        "last_high": round(float(last["high"]), 4),
        "last_low": round(float(last["low"]), 4),
        "atr14": round(last_atr, 4),
        "ema50": round(float(last["ema_fast"]), 4),
        "ema200": round(float(last["ema_slow"]), 4),
        "hh_count": trend["hh_count"],
        "hl_count": trend["hl_count"],
        "last_ph_price": round(trend["last_ph"][1], 4) if trend["last_ph"] else None,
        "last_pl_price": round(trend["last_pl"][1], 4) if trend["last_pl"] else None,
        "recent_high_20": round(recent_high_20, 4) if recent_high_20 is not None else None,
        "recent_high_252": round(recent_high_252, 4) if recent_high_252 is not None else None,
        "lower_tail_ratio": sig["lower_tail_ratio"],
        "score": breakdown["total"],
        "score_trend": breakdown["trend"],
        "score_support_quality": breakdown["support_quality"],
        "score_reaction": breakdown["reaction"],
        "score_liquidity": breakdown["liquidity"],
        "score_room": breakdown["room"],
        "reasons": ";".join(sig["reasons"]),
    }


def main():
    parser = argparse.ArgumentParser(description="S&P 500 support buy alert — Signal Scan")
    parser.add_argument("--output-dir", default=CFG.out_dir)
    parser.add_argument("--min-score", type=float, default=CFG.min_signal_score)
    parser.add_argument(
        "--no-telegram",
        action="store_true",
        help="Disable Telegram notifications even if credentials are set.",
    )
    args = parser.parse_args()

    if not os.path.exists(CFG.watchlist_path):
        print(f"Watchlist not found at {CFG.watchlist_path}. Run universe scan first.")
        sys.exit(1)

    with open(CFG.watchlist_path) as f:
        watchlist = json.load(f)

    cache = load_cache(CFG.bars_cache)
    if cache.empty:
        print("Bar cache is empty. Run universe scan first.")
        sys.exit(1)

    items: List[Dict] = watchlist.get("primary", []) + watchlist.get("monitor", [])
    print(f"Processing {len(items)} watchlist items (min_score={args.min_score})...")

    signals: List[Dict] = []
    errors = 0
    for item in items:
        try:
            r = process_item(item, cache)
            if r is not None:
                signals.append(r)
        except Exception as e:
            errors += 1
            print(f"  {item.get('ticker','?')}: error ({e})")

    # Filter by min score & sort
    signals = [s for s in signals if s["score"] >= args.min_score]
    signals.sort(key=lambda x: x["score"], reverse=True)

    print(f"\nGenerated {len(signals)} signals (errors={errors})")
    for s in signals[:25]:
        print(
            f"  {s['ticker']:6s} cat={s['support_category']:7s} "
            f"type={s['support_type']:16s} score={s['score']:5.1f} "
            f"close={s['last_close']:8.2f} zone=[{s['zone_low']:.2f}, {s['zone_high']:.2f}]"
        )

    # Always write the CSV (even when empty) so downloads are predictable.
    os.makedirs(args.output_dir, exist_ok=True)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    csv_path = os.path.join(args.output_dir, f"signals_{today_str}.csv")

    if signals:
        pd.DataFrame(signals)[SIGNAL_COLUMNS].to_csv(csv_path, index=False)
    else:
        pd.DataFrame(columns=SIGNAL_COLUMNS).to_csv(csv_path, index=False)
    print(f"Saved {csv_path}")

    # Also write a "latest" convenience copy.
    latest_path = os.path.join(args.output_dir, "signals_latest.csv")
    try:
        import shutil
        shutil.copyfile(csv_path, latest_path)
        print(f"Saved {latest_path}")
    except Exception as e:
        print(f"Warning: could not write latest copy: {e}")

    # ─── Telegram notification ───────────────────────────────────────
    if args.no_telegram:
        print("Telegram notifications disabled via --no-telegram.")
    else:
        notifier = TelegramNotifier(
            bot_token=CFG.telegram_bot_token,
            chat_id=CFG.telegram_chat_id,
        )
        if not notifier.enabled:
            print("Telegram notifications skipped (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set).")
        else:
            try:
                ok = notifier.send_signals(
                    signals,
                    scan_date=today_str,
                    notify_on_empty=CFG.telegram_notify_on_empty,
                    max_signals=CFG.telegram_max_signals,
                )
                if ok:
                    if signals:
                        print(f"Telegram: sent {len(signals)} signal(s).")
                    elif CFG.telegram_notify_on_empty:
                        print("Telegram: sent empty-day notice.")
                    else:
                        print("Telegram: no signals — skipping message (set TELEGRAM_NOTIFY_ON_EMPTY=1 to send).")
                else:
                    print("Telegram: send returned failure (see log above).")
            except Exception as e:
                # Never let a Telegram issue fail the job.
                print(f"Telegram: unexpected error ({e}) — scan results still saved to CSV.")


if __name__ == "__main__":
    main()
