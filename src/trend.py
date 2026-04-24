"""Higher Highs + Higher Lows uptrend detection.

Design note:
  A naive "strictly-ascending last 2 pivots" rule is too fragile — a small noise
  peak during a pullback can create a "lower high" that false-invalidates a
  perfectly intact uptrend structure.

  Instead, we use a window-based check:
    HH = max(pivot highs in the recent half) > max(pivot highs in the older half)
    HL = latest pivot low strictly above the previous pivot low
  Plus: the OVERALL max pivot high must be within the recent half (otherwise
  the trend peaked long ago and is just drifting).

  This matches how traders read a chart — "we made a higher high, then a
  higher low, and we're currently testing that higher low" — without being
  fooled by minor retracement peaks.
"""
from typing import Dict, List, Tuple


def detect_trend(
    pivot_highs: List[Tuple[int, float]],
    pivot_lows: List[Tuple[int, float]],
    lookback_pivots: int = 4,
) -> Dict:
    result = {
        "trend": "none",
        "trend_valid": False,
        "hh": False,
        "hl": False,
        "hh_count": 0,          # rising transitions in recent window (for scoring)
        "hl_count": 0,
        "last_ph": None,
        "last_pl": None,
        "prev_pl": None,
        "max_ph": None,
    }

    if len(pivot_highs) < 2 or len(pivot_lows) < 2:
        return result

    # Use up to last `lookback_pivots` pivots of each kind
    recent_ph = pivot_highs[-lookback_pivots:]
    recent_pl = pivot_lows[-lookback_pivots:]

    # --- HH check ---
    # Split into older-half / newer-half, check that the newer half's max is higher.
    mid = max(1, len(recent_ph) // 2)
    older_ph_max = max(p for _, p in recent_ph[:mid])
    newer_ph_max = max(p for _, p in recent_ph[mid:])
    hh = newer_ph_max > older_ph_max

    # The all-time max pivot high within the lookback must be in the newer half.
    # Otherwise the trend peaked long ago and is no longer valid as an uptrend.
    max_ph_idx, max_ph_price = max(recent_ph, key=lambda x: x[1])
    newer_half_start_idx = recent_ph[mid][0]
    max_ph_is_recent = max_ph_idx >= newer_half_start_idx

    # --- HL check ---
    # Strict: latest PL > previous PL
    hl = pivot_lows[-1][1] > pivot_lows[-2][1]

    # Count rising transitions (for scoring)
    hh_count = sum(
        1 for i in range(len(recent_ph) - 1)
        if recent_ph[i + 1][1] > recent_ph[i][1]
    )
    hl_count = sum(
        1 for i in range(len(recent_pl) - 1)
        if recent_pl[i + 1][1] > recent_pl[i][1]
    )

    trend_valid = bool(hh and hl and max_ph_is_recent)

    result.update({
        "trend": "uptrend" if trend_valid else "none",
        "trend_valid": trend_valid,
        "hh": bool(hh),
        "hl": bool(hl),
        "hh_count": hh_count,
        "hl_count": hl_count,
        "last_ph": pivot_highs[-1],
        "last_pl": pivot_lows[-1],
        "prev_pl": pivot_lows[-2],
        "max_ph": (max_ph_idx, max_ph_price),
    })
    return result
