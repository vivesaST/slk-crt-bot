"""
Structure + external BO (Malaysian SNR storyline)

BO: body CLOSE beyond last swing that existed BEFORE HTF rejection.
Wick does not count. Internal post-rejection swings are not the break level.
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
    kind: str


@dataclass
class StructureBreak:
    direction: str
    break_price: float
    break_time: pd.Timestamp
    break_index: int
    is_external: bool = True
    level_time: Optional[pd.Timestamp] = None
    swept_level: Optional[float] = None
    is_continuation: bool = False


@dataclass
class HTFRange:
    high: float
    low: float
    high_time: Optional[pd.Timestamp]
    low_time: Optional[pd.Timestamp]
    bias: str
    last_close: float


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
    if df is None or len(df) < lookback + 5:
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


def detect_htf_range(df: pd.DataFrame, lookback: int = 50) -> Optional[HTFRange]:
    if df is None or len(df) < 15:
        return None
    recent = df.iloc[-lookback:] if len(df) >= lookback else df
    sh = find_swing_highs(recent, 2, 2)
    sl = find_swing_lows(recent, 2, 2)
    if sh and sl:
        top = max(sh, key=lambda x: x.price)
        bot = min(sl, key=lambda x: x.price)
        hi, hi_t = top.price, top.timestamp
        lo, lo_t = bot.price, bot.timestamp
    else:
        hi = float(recent["high"].max())
        lo = float(recent["low"].min())
        hi_t = recent["high"].idxmax()
        lo_t = recent["low"].idxmin()
    if hi <= lo:
        return None
    last_c = float(df["close"].iloc[-1])
    span = hi - lo
    pos = (last_c - lo) / span
    trend = determine_trend(df, min(25, len(df) - 2))
    bias = "NEUTRAL"
    if trend == Trend.BULLISH:
        bias = "BUY"
    elif trend == Trend.BEARISH:
        bias = "SELL"
    else:
        if pos <= 0.40:
            bias = "BUY"
        elif pos >= 0.60:
            bias = "SELL"
    return HTFRange(hi, lo, hi_t, lo_t, bias, last_c)


def _align_ts(ts, idx_tz):
    ts = pd.Timestamp(ts)
    if idx_tz is not None:
        if ts.tzinfo is None:
            return ts.tz_localize(idx_tz)
        return ts.tz_convert(idx_tz)
    if ts.tzinfo is not None:
        return ts.tz_localize(None)
    return ts


def detect_snr_breakout(
    df_ltf: pd.DataFrame,
    direction: str,
    rejection_time,
    max_age_bars: int = 12,
) -> Optional[StructureBreak]:
    """External body BO after HTF rejection."""
    if df_ltf is None or len(df_ltf) < 15:
        return None

    rejection_time = _align_ts(rejection_time, df_ltf.index.tz)
    left, right = 2, 2
    sh = find_swing_highs(df_ltf, left, right)
    sl = find_swing_lows(df_ltf, left, right)

    if direction == "SELL":
        prior = [s for s in sl if s.timestamp < rejection_time]
        if not prior:
            return None
        external = max(prior, key=lambda x: x.index)
        break_side = "below"
    else:
        prior = [s for s in sh if s.timestamp < rejection_time]
        if not prior:
            return None
        external = max(prior, key=lambda x: x.index)
        break_side = "above"

    level = external.price
    n = len(df_ltf)
    start_i = max(external.index + 1, n - max_age_bars)
    best = None

    for i in range(start_i, n):
        if df_ltf.index[i] < rejection_time:
            continue
        c = float(df_ltf["close"].iloc[i])
        if break_side == "above" and c > level:
            best = StructureBreak(
                "bullish", level, df_ltf.index[i], i, True, external.timestamp, level, False
            )
        elif break_side == "below" and c < level:
            best = StructureBreak(
                "bearish", level, df_ltf.index[i], i, True, external.timestamp, level, False
            )

    if best is None:
        return None
    last_c = float(df_ltf["close"].iloc[-1])
    if best.direction == "bullish" and last_c < best.break_price:
        return None
    if best.direction == "bearish" and last_c > best.break_price:
        return None
    return best


def detect_continuation_breaks(
    df_ltf: pd.DataFrame,
    direction: str,
    max_age_bars: int = 6,
) -> List[StructureBreak]:
    if df_ltf is None or len(df_ltf) < 12:
        return []
    left, right = 1, 1
    sh = find_swing_highs(df_ltf, left, right)
    sl = find_swing_lows(df_ltf, left, right)
    n = len(df_ltf)
    start_i = max(right + 1, n - max_age_bars)
    results = []
    for i in range(start_i, n):
        c = float(df_ltf["close"].iloc[i])
        if direction == "BUY":
            prior = [s for s in sh if s.index < i - right]
            if not prior:
                continue
            swing = max(prior, key=lambda x: x.index)
            if c > swing.price:
                results.append(
                    StructureBreak(
                        "bullish", swing.price, df_ltf.index[i], i, True,
                        swing.timestamp, swing.price, True
                    )
                )
        else:
            prior = [s for s in sl if s.index < i - right]
            if not prior:
                continue
            swing = max(prior, key=lambda x: x.index)
            if c < swing.price:
                results.append(
                    StructureBreak(
                        "bearish", swing.price, df_ltf.index[i], i, True,
                        swing.timestamp, swing.price, True
                    )
                )
    last_c = float(df_ltf["close"].iloc[-1])
    held = []
    for b in results:
        if b.direction == "bullish" and last_c >= b.break_price:
            held.append(b)
        elif b.direction == "bearish" and last_c <= b.break_price:
            held.append(b)
    return held[-3:] if held else []


def detect_crt_sweep(df: pd.DataFrame) -> Optional[dict]:
    """
    CRT: current/recent candle sweeps previous candle high or low, closes back inside.
    Also tags PDH/PDL style when looking at daily.
    """
    if df is None or len(df) < 3:
        return None

    # check last 2 closed-style bars (prefer -2 as last fully formed if -1 is forming)
    for i in range(len(df) - 1, max(len(df) - 3, 0), -1):
        if i < 1:
            continue
        prev_h = float(df["high"].iloc[i - 1])
        prev_l = float(df["low"].iloc[i - 1])
        h = float(df["high"].iloc[i])
        l = float(df["low"].iloc[i])
        c = float(df["close"].iloc[i])

        # Bearish CRT: sweep prev high, close back below prev high
        if h > prev_h and c < prev_h:
            return {
                "type": "bearish_crt",
                "direction": "SELL",
                "swept": prev_h,
                "side": "high",
                "close": c,
                "time": df.index[i],
                "index": i,
                "prev_high": prev_h,
                "prev_low": prev_l,
            }
        # Bullish CRT: sweep prev low, close back above prev low
        if l < prev_l and c > prev_l:
            return {
                "type": "bullish_crt",
                "direction": "BUY",
                "swept": prev_l,
                "side": "low",
                "close": c,
                "time": df.index[i],
                "index": i,
                "prev_high": prev_h,
                "prev_low": prev_l,
            }
    return None


def detect_external_break(df: pd.DataFrame, max_age_bars: int = 2) -> Optional[StructureBreak]:
    if len(df) < 20:
        return None
    left, right = 2, 2
    sh = find_swing_highs(df, left, right)
    sl = find_swing_lows(df, left, right)
    if not sh or not sl:
        return None
    n = len(df)
    start_i = max(right + 1, n - max_age_bars)
    best = None
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
