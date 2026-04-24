"""Scoring tests — regression guards for the P0 fixes.

These tests protect the two fixes just applied:
  1. support_quality now REWARDS strong reclaim bars (was 0 before).
  2. room_to_resistance ignores noise-level resistances within 0.5 × ATR
     of close, so a tiny consolidation peak no longer zeroes the score.

Plus: verifies that the default min_signal_score allows a valid synthetic
signal through — the exact gap that the code review identified.

Run:
    python -m tests.test_scoring
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import CFG
from src.scoring import compute_score_breakdown
from src.support import SupportZone


def _base_zone(price: float = 100.0, width: float = 1.0) -> SupportZone:
    return SupportZone(
        support_type="higher_low",
        price=price,
        zone_low=price - width / 2,
        zone_high=price + width / 2,
        pivot_index=0,
        pivot_date="2026-01-01",
    )


def _base_signal() -> dict:
    return {
        "triggered": True,
        "touched": True,
        "held": True,
        "recovered": True,
        "bullish_body": True,
        "bullish_vs_prev": True,
        "lower_tail_ratio": 0.25,
    }


def test_support_quality_rewards_strong_reclaim():
    """A bar that closes 1 ATR above zone_high must score at/near 100 on support_quality."""
    zone = _base_zone(price=100.0, width=1.0)   # zone = [99.5, 100.5]
    atr_val = 2.0
    close = 100.5 + atr_val * 1.0                # 1 ATR above zone_high

    features = {
        "hh_count": 2, "hl_count": 2,
        "last_close": close, "atr14": atr_val,
        "last_ph_price": None, "recent_high_20": None, "recent_high_252": None,
        "avg_dollar_volume": 50_000_000,
    }
    b = compute_score_breakdown(features, zone, _base_signal())
    assert b["support_quality"] == 100.0, f"expected 100, got {b['support_quality']}"


def test_support_quality_decent_inside_zone():
    """A bar that closes inside the zone at the midpoint should still score decently."""
    zone = _base_zone(price=100.0, width=1.0)
    close = 100.0                                 # exact zone_mid

    features = {
        "hh_count": 2, "hl_count": 2,
        "last_close": close, "atr14": 2.0,
        "last_ph_price": None, "recent_high_20": None, "recent_high_252": None,
        "avg_dollar_volume": 50_000_000,
    }
    b = compute_score_breakdown(features, zone, _base_signal())
    assert 50.0 <= b["support_quality"] <= 80.0, \
        f"inside-zone close should score 50-80, got {b['support_quality']}"


def test_support_quality_penalizes_zone_break():
    """A bar that closes well below zone_low should score very low on support_quality."""
    zone = _base_zone(price=100.0, width=1.0)
    atr_val = 2.0
    close = zone.zone_low - atr_val * 0.3         # below zone by 0.3 ATR

    features = {
        "hh_count": 2, "hl_count": 2,
        "last_close": close, "atr14": atr_val,
        "last_ph_price": None, "recent_high_20": None, "recent_high_252": None,
        "avg_dollar_volume": 50_000_000,
    }
    b = compute_score_breakdown(features, zone, _base_signal())
    assert b["support_quality"] < 30.0, \
        f"below-zone close should be heavily penalized, got {b['support_quality']}"


def test_room_ignores_noise_peak_within_atr_filter():
    """A pivot high within 0.5 ATR above close must NOT zero the room score."""
    zone = _base_zone(price=100.0, width=1.0)
    atr_val = 2.0
    close = 105.0
    noise_peak = 105.2         # 0.1 ATR above close → should be filtered out
    real_resistance = 115.0    # 9.5% above close → meaningful

    features = {
        "hh_count": 2, "hl_count": 2,
        "last_close": close, "atr14": atr_val,
        "last_ph_price": noise_peak,
        "recent_high_20": noise_peak,
        "recent_high_252": real_resistance,
        "avg_dollar_volume": 50_000_000,
    }
    b = compute_score_breakdown(features, zone, _base_signal())
    # 9.5% room maps to ~78 in the piecewise curve
    assert b["room"] >= 60.0, \
        f"room should reflect real resistance at 9.5%, got {b['room']}"


def test_room_whitespace_when_all_candidates_below():
    """When close is above every candidate, room returns the whitespace value."""
    zone = _base_zone(price=100.0, width=1.0)
    features = {
        "hh_count": 2, "hl_count": 2,
        "last_close": 150.0, "atr14": 2.0,
        "last_ph_price": 120.0,
        "recent_high_20": 130.0,
        "recent_high_252": 140.0,
        "avg_dollar_volume": 50_000_000,
    }
    b = compute_score_breakdown(features, zone, _base_signal())
    assert b["room"] >= 80.0, f"whitespace should be high, got {b['room']}"


def test_default_threshold_accepts_strong_signal():
    """The exact gap the review flagged: default min_signal_score must pass a strong valid signal.

    Build a best-case scenario: valid trend, reclaim 1 ATR above zone_high,
    all bullish reaction flags, $50M liquidity, 10% room to meaningful resistance.
    This should total WELL above 60 — if it doesn't, the whole gating system
    is miscalibrated.
    """
    zone = _base_zone(price=100.0, width=1.0)
    atr_val = 2.0
    close = zone.zone_high + atr_val * 1.0

    features = {
        "hh_count": 3, "hl_count": 3,
        "last_close": close, "atr14": atr_val,
        "last_ph_price": close * 1.005,     # tiny peak, should be filtered out
        "recent_high_20": close * 1.02,     # 2% above, real
        "recent_high_252": close * 1.10,    # 10% above, major
        "avg_dollar_volume": 50_000_000,
    }
    b = compute_score_breakdown(features, zone, _base_signal())
    assert b["total"] >= CFG.min_signal_score, (
        f"strong signal total={b['total']} but min_signal_score={CFG.min_signal_score} — "
        f"breakdown={b}"
    )


def test_support_quality_continuous_at_zone_high():
    """v2.1 regression: no score drop exactly at `close == zone_high`.

    Previous v2 had inside-zone top = 75 and reclaim-bottom = 70, creating
    a 5-point drop for a *stronger* close. The fix aligns both branches at 75.
    """
    zone = _base_zone(price=100.0, width=1.0)      # zone_high = 100.5
    atr_val = 2.0

    def breakdown(close):
        features = {
            "hh_count": 2, "hl_count": 2,
            "last_close": close, "atr14": atr_val,
            "last_ph_price": None, "recent_high_20": None, "recent_high_252": None,
            "avg_dollar_volume": 50_000_000,
        }
        return compute_score_breakdown(features, zone, _base_signal())

    below = breakdown(zone.zone_high - 0.001)["support_quality"]
    at = breakdown(zone.zone_high)["support_quality"]
    above = breakdown(zone.zone_high + 0.001)["support_quality"]

    # Monotonic non-decreasing across the boundary (tolerance for float arithmetic).
    assert below <= at + 0.01, f"continuity broken: below={below}, at={at}"
    assert at <= above + 0.01, f"continuity broken: at={at}, above={above}"
    # And no 5-point regression like v2 had.
    assert abs(at - below) < 1.0, f"expected near-continuous, got {below} -> {at}"


def test_room_continuous_across_noise_threshold():
    """v2.1 regression: no score jump as a single resistance crosses the ATR threshold.

    Previously: close=100, ATR=2. Resistance at 100.99/101.00 scored 90 (empty
    above_threshold → whitespace), resistance at 101.01 scored ~15.2 (nearest
    above threshold). The new fallback treats 'only noise-band resistance'
    as 'use the nearest anyway', keeping the curve continuous.
    """
    close = 100.0
    atr_val = 2.0
    # threshold = close + 0.5 * ATR = 101.0

    def room(resistance):
        features = {
            "hh_count": 2, "hl_count": 2,
            "last_close": close, "atr14": atr_val,
            "last_ph_price": resistance,
            "recent_high_20": None, "recent_high_252": None,
            "avg_dollar_volume": 50_000_000,
        }
        zone = _base_zone(price=95.0, width=1.0)
        return compute_score_breakdown(features, zone, _base_signal())["room"]

    r_below = room(100.99)  # below threshold, inside noise band
    r_at = room(101.00)     # exactly at threshold
    r_above = room(101.01)  # just above threshold

    # All three should be close (~15 pts, since room_pct ~ 1%), not a cliff.
    assert abs(r_at - r_below) < 2.0, \
        f"room jump at threshold-: below={r_below}, at={r_at}"
    assert abs(r_above - r_at) < 2.0, \
        f"room jump at threshold+: at={r_at}, above={r_above}"
    # All should reflect "close is right under resistance", i.e. low room.
    assert all(r < 20.0 for r in (r_below, r_at, r_above)), \
        f"expected low room (~15) in all three cases, got {r_below}/{r_at}/{r_above}"


def test_room_whitespace_only_when_truly_above_all():
    """v2.1 regression: whitespace=90 triggers only when NO resistance is above close,
    not when resistance exists but sits inside the noise band.
    """
    close = 100.0
    zone = _base_zone(price=95.0, width=1.0)

    # Case A: genuine whitespace — all candidates below close.
    features_a = {
        "hh_count": 2, "hl_count": 2,
        "last_close": close, "atr14": 2.0,
        "last_ph_price": 90.0, "recent_high_20": 95.0, "recent_high_252": 99.0,
        "avg_dollar_volume": 50_000_000,
    }
    room_a = compute_score_breakdown(features_a, zone, _base_signal())["room"]
    assert room_a == 90.0, f"whitespace should be 90, got {room_a}"

    # Case B: resistance exists just above close but inside noise band.
    # Must NOT be treated as whitespace.
    features_b = dict(features_a, last_ph_price=100.5)  # 0.25 ATR above
    room_b = compute_score_breakdown(features_b, zone, _base_signal())["room"]
    assert room_b < 20.0, (
        f"noise-band resistance should give low room (~7-8), not whitespace. got {room_b}"
    )


def main():
    tests = [
        test_support_quality_rewards_strong_reclaim,
        test_support_quality_decent_inside_zone,
        test_support_quality_penalizes_zone_break,
        test_support_quality_continuous_at_zone_high,
        test_room_ignores_noise_peak_within_atr_filter,
        test_room_whitespace_when_all_candidates_below,
        test_room_continuous_across_noise_threshold,
        test_room_whitespace_only_when_truly_above_all,
        test_default_threshold_accepts_strong_signal,
    ]
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except AssertionError as e:
            print(f"  [FAIL] {t.__name__}: {e}")
            sys.exit(1)
    print(f"\n[OK] all {len(tests)} scoring tests passed.")


if __name__ == "__main__":
    main()
