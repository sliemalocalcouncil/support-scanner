"""Support buy signal logic.

Trigger on the latest bar when all of:
  - low touched or entered the support zone (low <= zone_high)
  - close held above zone_low (not broken down)
  - close recovered at least the zone midpoint
  - bullish close (close > open OR close > previous close OR strong lower tail)
"""
from typing import Dict

import pandas as pd

from src.support import SupportZone


def detect_buy_signal(df: pd.DataFrame, zone: SupportZone) -> Dict:
    if len(df) < 2:
        return {"triggered": False, "reasons": ["insufficient_bars"]}

    last = df.iloc[-1]
    prev = df.iloc[-2]

    open_ = float(last["open"])
    high = float(last["high"])
    low = float(last["low"])
    close = float(last["close"])
    prev_close = float(prev["close"])

    zone_low = zone.zone_low
    zone_high = zone.zone_high
    zone_mid = (zone_low + zone_high) / 2.0

    # Proximity checks
    touched = low <= zone_high
    held = close >= zone_low
    recovered = close >= zone_mid

    # Bullishness checks
    bullish_body = close > open_
    bullish_vs_prev = close > prev_close

    # Lower tail rejection
    bar_range = high - low
    if bar_range > 0:
        lower_tail = min(close, open_) - low
        lower_tail_ratio = lower_tail / bar_range
    else:
        lower_tail_ratio = 0.0
    strong_tail = lower_tail_ratio >= 0.4

    triggered = touched and held and recovered and (bullish_body or bullish_vs_prev or strong_tail)

    reasons = []
    if touched: reasons.append("price_touched_zone")
    if held: reasons.append("close_held_above_zone_low")
    if recovered: reasons.append("close_recovered_zone_mid")
    if bullish_body: reasons.append("bullish_candle_body")
    if bullish_vs_prev: reasons.append("close_above_prev_close")
    if strong_tail: reasons.append("strong_lower_tail_rejection")

    return {
        "triggered": triggered,
        "touched": touched,
        "held": held,
        "recovered": recovered,
        "bullish_body": bullish_body,
        "bullish_vs_prev": bullish_vs_prev,
        "lower_tail_ratio": round(lower_tail_ratio, 3),
        "reasons": reasons,
    }
