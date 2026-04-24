"""Pivot high / pivot low detection.

A pivot at index i is confirmed only when k bars on the right have been seen.
This means pivots are always lagged by k bars — which is intentional and
matches the spec's principle of "confirmed pivot based" design.
"""
from typing import List, Tuple

import numpy as np
import pandas as pd


def find_pivots(df: pd.DataFrame, k: int = 4) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
    """Return (pivot_highs, pivot_lows) as lists of (index, price).

    Pivot high at i: high[i] > max(high[i-k:i]) AND high[i] >= max(high[i+1:i+k+1])
    Pivot low  at i: low[i]  < min(low[i-k:i])  AND low[i]  <= min(low[i+1:i+k+1])
    (strict-left / non-strict-right comparison handles flat tops/bottoms gracefully)
    """
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    n = len(df)

    pivot_highs: List[Tuple[int, float]] = []
    pivot_lows: List[Tuple[int, float]] = []

    if n < 2 * k + 1:
        return pivot_highs, pivot_lows

    for i in range(k, n - k):
        left_high_max = highs[i - k:i].max()
        right_high_max = highs[i + 1:i + k + 1].max()
        if highs[i] > left_high_max and highs[i] >= right_high_max:
            pivot_highs.append((i, float(highs[i])))

        left_low_min = lows[i - k:i].min()
        right_low_min = lows[i + 1:i + k + 1].min()
        if lows[i] < left_low_min and lows[i] <= right_low_min:
            pivot_lows.append((i, float(lows[i])))

    return pivot_highs, pivot_lows


def filter_alternating(
    pivot_highs: List[Tuple[int, float]],
    pivot_lows: List[Tuple[int, float]],
) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
    """Merge runs of same-type pivots into a single extreme pivot.

    When two pivot highs appear consecutively (no pivot low between them),
    keep the higher one. Same for consecutive pivot lows (keep the lower).
    This cleans up noisy local extrema during retracements, yielding a
    clean alternating H, L, H, L, ... sequence.
    """
    merged: List[Tuple[int, float, str]] = []
    merged.extend((i, p, "H") for i, p in pivot_highs)
    merged.extend((i, p, "L") for i, p in pivot_lows)
    merged.sort(key=lambda x: x[0])

    if not merged:
        return [], []

    out: List[Tuple[int, float, str]] = [merged[0]]
    for cur in merged[1:]:
        prev = out[-1]
        if cur[2] == prev[2]:
            # Same type: keep whichever is more extreme
            if (cur[2] == "H" and cur[1] > prev[1]) or (cur[2] == "L" and cur[1] < prev[1]):
                out[-1] = cur
        else:
            out.append(cur)

    ph = [(i, p) for i, p, t in out if t == "H"]
    pl = [(i, p) for i, p, t in out if t == "L"]
    return ph, pl


def filter_by_swing_amplitude(
    pivot_highs: List[Tuple[int, float]],
    pivot_lows: List[Tuple[int, float]],
    min_swing: float,
) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
    """Remove pivot pairs whose swing amplitude is below `min_swing`.

    After alternation, we have a sequence H-L-H-L-... . A "swing" is the price
    difference between adjacent opposite-type pivots. If a swing is too small,
    both endpoints of that swing are treated as noise and dropped together,
    then we re-run alternation (because dropping two consecutive entries can
    make same-type pivots adjacent).
    """
    merged: List[Tuple[int, float, str]] = []
    merged.extend((i, p, "H") for i, p in pivot_highs)
    merged.extend((i, p, "L") for i, p in pivot_lows)
    merged.sort(key=lambda x: x[0])

    if len(merged) < 2 or min_swing <= 0:
        return pivot_highs, pivot_lows

    changed = True
    while changed and len(merged) >= 2:
        changed = False
        # Find the smallest swing
        smallest_i = -1
        smallest_amp = float("inf")
        for i in range(len(merged) - 1):
            if merged[i][2] == merged[i + 1][2]:
                continue  # not a swing (same type); will be fixed by re-alternation
            amp = abs(merged[i + 1][1] - merged[i][1])
            if amp < smallest_amp:
                smallest_amp = amp
                smallest_i = i

        if smallest_i >= 0 and smallest_amp < min_swing:
            # Drop the smaller-amplitude pair
            merged = merged[:smallest_i] + merged[smallest_i + 2:]
            changed = True
            # Re-run alternation on the new sequence
            if merged:
                ph_tmp = [(i, p) for i, p, t in merged if t == "H"]
                pl_tmp = [(i, p) for i, p, t in merged if t == "L"]
                ph_tmp, pl_tmp = filter_alternating(ph_tmp, pl_tmp)
                merged = [(i, p, "H") for i, p in ph_tmp] + [(i, p, "L") for i, p in pl_tmp]
                merged.sort(key=lambda x: x[0])

    ph = [(i, p) for i, p, t in merged if t == "H"]
    pl = [(i, p) for i, p, t in merged if t == "L"]
    return ph, pl
