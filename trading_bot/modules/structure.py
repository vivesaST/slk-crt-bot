"""Market structure — swings, trend, external BO"""
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
    is_external: bool = True


def find_swing_highs(df: pd.DataFrame, left: int = 3, right: int = 3) -> List[SwingPoint]:
    swings = []
    highs = df["high"].values
    times = df.index
    for i in range(left, len(df) - right):
        if highs[i] == max(highs[i - left : i + right + 1]):
            swings.append(SwingPoint(i, float(highs[i]), times[i], "high"))
    return swings


def find_swing_lows(df: pd.DataFrame, left: int = 3, right: int = 3) -> List[SwingPoint]:
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


def detect_external_break(df: pd.DataFrame) -> Optional[StructureBreak]:
    if len(df) < 20:
        return None
    sh = find_swing_highs(df)
    sl = find_swing_lows(df)
    if not sh or not sl:
        return None
    last_close = float(df["close"].iloc[-1])
    last_high = float(df["high"].iloc[-1])
    last_low = float(df["low"].iloc[-1])
    last_time = df.index[-1]
    recent_h = [s for s in sh if s.index < len(df) - 2]
    recent_l = [s for s in sl if s.index < len(df) - 2]
    if not recent_h or not recent_l:
        return None
    last_sh = max(recent_h, key=lambda x: x.index)
    last_sl = max(recent_l, key=lambda x: x.index)
    if last_close > last_sh.price and last_high > last_sh.price:
        return StructureBreak("bullish", last_sh.price, last_time, True)
    if last_close < last_sl.price and last_low < last_sl.price:
        return StructureBreak("bearish", last_sl.price, last_time, True)
    return None
