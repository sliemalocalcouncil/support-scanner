"""Weighted score (0 - 100) for ranking signals.

Weights (sum = 1.0):
  trend_score         0.30
  support_quality     0.25
  reaction_strength   0.20
  liquidity           0.10
  room_to_resistance  0.15

Design changes from the MVP:

1. support_quality — NO LONGER penalizes strong reclaim bars.
   Previously: `100 * (1 - abs(close - zone_mid) / zone_width)` which drove the
   score to 0 as soon as `close` moved ~1 zone-width away from zone_mid — the
   exact behavior of a strong bullish rejection bar (which is what we WANT).
   New design scores three regimes separately:
     - close >= zone_high:  reclaim-above-zone (REWARDED). The farther above
       zone_high (normalized by ATR), the higher — up to 100. A close right
       at zone_high still earns 70 (clear reclaim with no excess).
     - zone_low <= close < zone_high: inside zone, scaled 50..75 by position.
     - close < zone_low: zone-break (heavily penalized). Usually a signal
       would not have triggered here, but if it did, score drops toward 0.

2. room_to_resistance — multi-level instead of only the latest pivot high.
   Previously used only `last_ph_price`, which is often a small/minor peak
   that vastly underestimates headroom. New design takes the NEAREST of:
     - last_ph_price   (immediate pivot resistance)
     - recent_high_20  (20-bar high)
     - recent_high_252 (~52-week high)
   …and applies a piecewise-linear curve that is much less punishing for
   near-term rooms (2-5%) but also reaches 100 sooner. If the close is
   already above all three candidate resistances (i.e., in whitespace),
   room is set to 90.

The function now returns a breakdown dict so callers can inspect components.
"""
from typing import Dict, Optional

from src.support import SupportZone


# -------- component scorers --------

def _trend_score(hh_count: int, hl_count: int) -> float:
    # 4 rising transitions across HH+HL saturates to 100.
    return min(100.0, (hh_count + hl_count) * 25.0)


def _support_quality_score(close: float, zone: SupportZone, atr_val: float) -> float:
    """See module docstring for the regime-based design.

    Continuity note: the inside-zone branch hits 75 at `zone_high`, and the
    reclaim branch starts at 75 at `zone_high` (then rises toward 100 at
    +1 ATR). This yields a continuous function across the zone boundary —
    an earlier version had 75/70 which caused a 5-point drop at the exact
    `close == zone_high` transition.
    """
    zone_low = zone.zone_low
    zone_high = zone.zone_high
    atr_safe = max(atr_val, close * 0.001)  # guard against zero ATR

    if close >= zone_high:
        # Reclaimed above the zone. Reward how far above, in ATR terms.
        # close == zone_high        => 75 (continuous with inside-zone top)
        # close == zone_high + 1 ATR => 100
        excess_atr = (close - zone_high) / atr_safe
        return min(100.0, 75.0 + excess_atr * 25.0)

    if close >= zone_low:
        # Inside the zone. 50 at zone_low, 75 at zone_high.
        zone_width = max(1e-9, zone_high - zone_low)
        position = (close - zone_low) / zone_width
        return 50.0 + position * 25.0

    # Below the zone: zone is breaking. Penalize by how far below.
    penetration_atr = (zone_low - close) / atr_safe
    return max(0.0, 40.0 - penetration_atr * 80.0)


def _reaction_score(signal_info: Dict) -> float:
    reaction = 0.0
    if signal_info.get("recovered"):
        reaction += 30.0
    if signal_info.get("bullish_body"):
        reaction += 20.0
    if signal_info.get("bullish_vs_prev"):
        reaction += 20.0
    reaction += min(30.0, signal_info.get("lower_tail_ratio", 0.0) * 75.0)
    return min(100.0, reaction)


def _liquidity_score(avg_dollar_volume: float) -> float:
    # $100M average daily $-volume saturates to 100.
    # Most S&P 500 names clear this easily — this component is a "is-it-liquid"
    # gate more than a ranking dimension. That's intentional; log scaling is
    # listed as a P1 item for when ranking compression becomes a problem.
    return min(100.0, avg_dollar_volume / 1_000_000.0)


def _room_to_resistance_score(
    close: float,
    atr_val: float,
    last_ph_price: Optional[float],
    recent_high_20: Optional[float],
    recent_high_252: Optional[float],
    min_room_atr: float = 0.5,
) -> float:
    """Piecewise-linear curve on the % distance to the nearest MEANINGFUL
    resistance above `close`.

    Three regimes, separated to avoid the boundary-jump issue that the
    review flagged in v2:

    A) No resistance candidate is above close at all  → true whitespace (90).
    B) Some resistance is above close but ALL above-close candidates sit
       inside the `min_room_atr × ATR` noise band → use the nearest anyway.
       This keeps the score continuous as a nearby resistance crosses the
       threshold (previously 100.99 → 90, 101.01 → 15.2 with ATR=2).
    C) At least one resistance is clearly above the noise band  → use the
       nearest of those (the meaningful case).
    """
    atr_safe = max(atr_val, close * 0.001)
    threshold = close + atr_safe * min_room_atr

    above_close = [
        r for r in (last_ph_price, recent_high_20, recent_high_252)
        if r is not None and r > close
    ]
    if not above_close:
        # Regime A: genuine whitespace overhead.
        return 90.0

    above_threshold = [r for r in above_close if r > threshold]
    # Regime C when available, else Regime B (continuous fallback).
    nearest = min(above_threshold) if above_threshold else min(above_close)

    room_pct = (nearest - close) / close * 100.0

    # Piecewise anchors: (% room, points)
    #   1%  -> 15
    #   2%  -> 30
    #   5%  -> 60
    #   10% -> 80
    #   20% -> 95
    #   30%+ -> 100
    if room_pct < 1.0:
        return room_pct * 15.0
    if room_pct < 2.0:
        return 15.0 + (room_pct - 1.0) * 15.0
    if room_pct < 5.0:
        return 30.0 + (room_pct - 2.0) * 10.0
    if room_pct < 10.0:
        return 60.0 + (room_pct - 5.0) * 4.0
    if room_pct < 20.0:
        return 80.0 + (room_pct - 10.0) * 1.5
    if room_pct < 30.0:
        return 95.0 + (room_pct - 20.0) * 0.5
    return 100.0


# -------- main API --------

def compute_score_breakdown(features: Dict, zone: SupportZone, signal_info: Dict) -> Dict:
    """Return score components + total. Kept separate for inspection/tuning."""
    close = float(features["last_close"])
    atr_val = float(features.get("atr14", close * 0.01))

    ts = _trend_score(
        int(features.get("hh_count", 0)),
        int(features.get("hl_count", 0)),
    )
    sq = _support_quality_score(close, zone, atr_val)
    rc = _reaction_score(signal_info)
    lq = _liquidity_score(float(features.get("avg_dollar_volume", 0.0)))
    rm = _room_to_resistance_score(
        close,
        atr_val,
        features.get("last_ph_price"),
        features.get("recent_high_20"),
        features.get("recent_high_252"),
    )

    total = ts * 0.30 + sq * 0.25 + rc * 0.20 + lq * 0.10 + rm * 0.15
    return {
        "trend": round(ts, 1),
        "support_quality": round(sq, 1),
        "reaction": round(rc, 1),
        "liquidity": round(lq, 1),
        "room": round(rm, 1),
        "total": round(total, 1),
    }


def compute_score(features: Dict, zone: SupportZone, signal_info: Dict) -> float:
    """Backward-compatible scalar score."""
    return compute_score_breakdown(features, zone, signal_info)["total"]
