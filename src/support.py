"""Support zone construction.

Type A — higher_low:
  The latest pivot low that is strictly greater than the previous pivot low.
  Zone = pivot_low ± buffer, buffer = ATR * buffer_mult.

Type B — breakout_retest:
  The most recent pivot high that the current close has already moved above
  (i.e., resistance that has flipped into support). Zone = pivot_high ± buffer.
"""
from dataclasses import dataclass, asdict
from typing import List, Optional, Tuple

import pandas as pd


@dataclass
class SupportZone:
    support_type: str          # "higher_low" | "breakout_retest"
    price: float
    zone_low: float
    zone_high: float
    pivot_index: int
    pivot_date: str

    def to_dict(self) -> dict:
        return asdict(self)


def higher_low_support(
    df: pd.DataFrame,
    pivot_lows: List[Tuple[int, float]],
    atr_val: float,
    buffer_mult: float = 0.25,
) -> Optional[SupportZone]:
    if len(pivot_lows) < 2:
        return None
    if pivot_lows[-1][1] <= pivot_lows[-2][1]:
        return None  # not a higher low
    idx, price = pivot_lows[-1]
    buffer = max(atr_val * buffer_mult, price * 0.001)  # floor buffer at 0.1% of price
    return SupportZone(
        support_type="higher_low",
        price=price,
        zone_low=price - buffer,
        zone_high=price + buffer,
        pivot_index=idx,
        pivot_date=str(df.iloc[idx]["date"]),
    )


def breakout_retest_support(
    df: pd.DataFrame,
    pivot_highs: List[Tuple[int, float]],
    last_close: float,
    atr_val: float,
    buffer_mult: float = 0.25,
    max_lookback_pivots: int = 5,
) -> Optional[SupportZone]:
    """Most recent pivot high that is below current close (= resistance flipped to support).

    Caps search to the last `max_lookback_pivots` pivot highs so we don't pick
    ancient levels that are no longer meaningful.
    """
    if not pivot_highs:
        return None
    candidates = pivot_highs[-max_lookback_pivots:]
    for idx, price in reversed(candidates):
        if last_close > price:
            buffer = max(atr_val * buffer_mult, price * 0.001)
            return SupportZone(
                support_type="breakout_retest",
                price=price,
                zone_low=price - buffer,
                zone_high=price + buffer,
                pivot_index=idx,
                pivot_date=str(df.iloc[idx]["date"]),
            )
    return None
