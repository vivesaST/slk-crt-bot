"""SLK Key Levels: A-shape, V-shape, Open/Close"""
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

import pandas as pd


class KeyLevelType(Enum):
    A_SHAPE = "A-shape"
    V_SHAPE = "V-shape"
    OPEN_CLOSE = "Open/Close"


@dataclass
class KeyLevel:
    level_type: KeyLevelType
    price: float
    candle_index: int
    timestamp: pd.Timestamp
    has_history: bool = False
    direction: str = ""
    strength: float = 1.0


def _close(o1, o2, tol):
    if o1 == 0 or o2 == 0:
        return False
    return abs(o1 - o2) / ((o1 + o2) / 2) <= tol


def detect_a_shape(df, tol=0.00025, lookback=50) -> List[KeyLevel]:
    levels = []
    if len(df) < 5:
        return levels
    o, h, c, t = df["open"].values, df["high"].values, df["close"].values, df.index
    start = max(1, len(df) - lookback)
    for i in range(start, len(df) - 1):
        if _close(o[i], o[i + 1], tol):
            avg = (o[i] + o[i + 1]) / 2
            if abs(max(h[i], h[i + 1]) - avg) / max(avg, 1e-9) < 0.003:
                levels.append(KeyLevel(KeyLevelType.A_SHAPE, avg, i, t[i], direction="sell", strength=1.2))
        if _close(c[i], o[i + 1], tol):
            avg = (c[i] + o[i + 1]) / 2
            if abs(max(h[i], h[i + 1]) - avg) / max(avg, 1e-9) < 0.003:
                levels.append(KeyLevel(KeyLevelType.A_SHAPE, avg, i, t[i], direction="sell", strength=1.1))
    return levels


def detect_v_shape(df, tol=0.00025, lookback=50) -> List[KeyLevel]:
    levels = []
    if len(df) < 5:
        return levels
    o, l, c, t = df["open"].values, df["low"].values, df["close"].values, df.index
    start = max(1, len(df) - lookback)
    for i in range(start, len(df) - 1):
        if _close(o[i], o[i + 1], tol):
            avg = (o[i] + o[i + 1]) / 2
            if abs(avg - min(l[i], l[i + 1])) / max(avg, 1e-9) < 0.003:
                levels.append(KeyLevel(KeyLevelType.V_SHAPE, avg, i, t[i], direction="buy", strength=1.2))
        if _close(c[i], o[i + 1], tol):
            avg = (c[i] + o[i + 1]) / 2
            if abs(avg - min(l[i], l[i + 1])) / max(avg, 1e-9) < 0.003:
                levels.append(KeyLevel(KeyLevelType.V_SHAPE, avg, i, t[i], direction="buy", strength=1.1))
    return levels


def add_history(levels, df, tol=0.0004):
    highs, lows = df["high"].values, df["low"].values
    for lvl in levels:
        touches = sum(
            1
            for i in range(len(df))
            if abs(highs[i] - lvl.price) / max(lvl.price, 1e-9) <= tol
            or abs(lows[i] - lvl.price) / max(lvl.price, 1e-9) <= tol
        )
        lvl.has_history = touches >= 1
        if lvl.has_history:
            lvl.strength += 0.3 * min(touches, 3)
    return levels


def get_key_levels(df, tol=0.00025, lookback=50) -> List[KeyLevel]:
    levels = detect_a_shape(df, tol, lookback) + detect_v_shape(df, tol, lookback)
    levels = add_history(levels, df)
    levels.sort(key=lambda x: x.strength, reverse=True)
    return levels


def nearest_kl(levels, price, max_pct=0.005) -> Optional[KeyLevel]:
    best, best_d = None, 1e9
    for lvl in levels:
        d = abs(lvl.price - price) / max(price, 1e-9)
        if d < best_d and d <= max_pct:
            best, best_d = lvl, d
    return best
