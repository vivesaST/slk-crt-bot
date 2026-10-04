"""
Market structure — Malaysian SNR breakout rules

BO definition (Pitchou.FX Malaysian SNR):
1. Body CLOSE beyond the level — wick alone does NOT count
2. Must be EXTERNAL — internal breakout does NOT count
3. External = break of the last structure level created BEFORE the HTF rejection
4. One TF lower than the rejection TF
5. No breakout = no storyline = no trade
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

import pandas as pd


class Trend(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass
class SwingPoint:
    index: int
    price: float
    timestamp: pd.Timestamp
    kind: str  # high | low


@dataclass
class StructureBreak:
    direction: str  # bullish | bearish
    break_price: float
    break_time: pd.Timestamp
    break_index: int
    is_external: bool = True
    level_time: Optional[pd.Timestamp] = None
    swept_level: Optional[float] = None  # previous candle high/low that was swept


def find_swing_highs(df: pd.DataFrame, left: int = 2, right: int = 2) -> List[SwingPoint]:
    swings = []
    highs = df["high"].values
    times = df.index
    for i in range(left, len(df) - right):
        if highs[i] == max(highs[i - left : i + right + 1]):
            swings.append(SwingPoint(i, float(highs[i]), times[i], "high"))
    return swings


def find_swing_lows(df: pd.DataFrame, left: int = 2, right: int = 2) -> List[SwingPoint]:
    swings = []
    lows = df["low"].values
    times = df.index
    for i in range(left, len(df) - right):
        if lows[i] == min(lows[i - left : i + right + 1]):
            swings.append(SwingPoint(i, float(lows[i]), times[i], "low"))
    return swings


def determine_trend(df: pd.DataFrame, lookback: int = 20) -> Trend:
    if len(df) < lookback + 5:
        return Trend.NEUTRAL
    recent = df.iloc[-lookback:]
    sh = find_swing_highs(recent, 2, 2)
    sl = find_swing_lows(recent, 2, 2)
    if len(sh) < 2 or len(sl) < 2:
        return Trend.NEUTRAL
    lh = sorted(sh, key=lambda x: x.index)[-2:]
    ll = sorted(sl, key=lambda x: x.index)[-2:]
    if lh[1].price > lh[0].price and ll[1].price > ll[0].price:
        return Trend.BULLISH
    if lh[1].price < lh[0].price and ll[1].price < ll[0].price:
        return Trend.BEARISH
    return Trend.NEUTRAL


def detect_snr_breakout(
    df_ltf: pd.DataFrame,
    direction: str,
    rejection_time: pd.Timestamp,
    max_age_bars: int = 12,
) -> Optional[StructureBreak]:
    """
    Malaysian SNR external breakout on the lower TF.

    - External level = last swing HIGH (BUY) or LOW (SELL) formed BEFORE rejection
    - After rejection: body CLOSE beyond that level
    - Wick-only does not count
    - Internal swings after rejection are NOT used as the break level
    """
    if df_ltf is None or len(df_ltf) < 15:
        return None

    rejection_time = pd.Timestamp(rejection_time)
    idx_tz = df_ltf.index.tz
    if idx_tz is not None:
        if rejection_time.tzinfo is None:
            rejection_time = rejection_time.tz_localize(idx_tz)
        else:
            rejection_time = rejection_time.tz_convert(idx_tz)
    else:
        if rejection_time.tzinfo is not None:
            rejection_time = rejection_time.tz_localize(None)

    left, right = 2, 2
    sh = find_swing_highs(df_ltf, left, right)
    sl = find_swing_lows(df_ltf, left, right)

    if direction == "SELL":
        # Bearish: break BELOW last swing low that existed before rejection
        prior = [s for s in sl if s.timestamp < rejection_time]
        if not prior:
            return None
        external = max(prior, key=lambda x: x.index)
        break_side = "below"
    else:
        # Bullish: break ABOVE last swing high that existed before rejection
        prior = [s for s in sh if s.timestamp < rejection_time]
        if not prior:
            return None
        external = max(prior, key=lambda x: x.index)
        break_side = "above"

    level = external.price
    n = len(df_ltf)
    start_i = max(external.index + 1, n - max_age_bars)

    best: Optional[StructureBreak] = None

    for i in range(start_i, n):
        if df_ltf.index[i] < rejection_time:
            continue

        c = float(df_ltf["close"].iloc[i])

        if break_side == "above":
            if c > level:
                best = StructureBreak(
                    direction="bullish",
                    break_price=level,
                    break_time=df_ltf.index[i],
                    break_index=i,
                    is_external=True,
                    level_time=external.timestamp,
                    swept_level=level,
                )
        else:
            if c < level:
                best = StructureBreak(
                    direction="bearish",
                    break_price=level,
                    break_time=df_ltf.index[i],
                    break_index=i,
                    is_external=True,
                    level_time=external.timestamp,
                    swept_level=level,
                )

    if best is None:
        return None

    # Still held on break side
    last_c = float(df_ltf["close"].iloc[-1])
    if best.direction == "bullish" and last_c < best.break_price:
        return None
    if best.direction == "bearish" and last_c > best.break_price:
        return None

    return best


def detect_external_break(df: pd.DataFrame, max_age_bars: int = 2) -> Optional[StructureBreak]:
    """Fallback BO without HTF rejection context. Prefer detect_snr_breakout."""
    if len(df) < 20:
        return None

    left, right = 2, 2
    sh = find_swing_highs(df, left, right)
    sl = find_swing_lows(df, left, right)
    if not sh or not sl:
        return None

    n = len(df)
    start_i = max(right + 1, n - max_age_bars)
    best: Optional[StructureBreak] = None

    for i in range(start_i, n):
        prior_h = [s for s in sh if s.index < i - right]
        prior_l = [s for s in sl if s.index < i - right]
        if not prior_h or not prior_l:
            continue
        swing_h = max(prior_h, key=lambda x: x.index)
        swing_l = max(prior_l, key=lambda x: x.index)
        c = float(df["close"].iloc[i])

        if c > swing_h.price:
            best = StructureBreak(
                "bullish", swing_h.price, df.index[i], i, True, swing_h.timestamp, swing_h.price
            )
        elif c < swing_l.price:
            best = StructureBreak(
                "bearish", swing_l.price, df.index[i], i, True, swing_l.timestamp, swing_l.price
            )

    if best is None:
        return None

    last_c = float(df["close"].iloc[-1])
    if best.direction == "bullish" and last_c < best.break_price:
        return None
    if best.direction == "bearish" and last_c > best.break_price:
        return None
    return best
