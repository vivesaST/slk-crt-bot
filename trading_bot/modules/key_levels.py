"""
Malaysian SNR Key Levels

From Pitchou.FX Malaysian SNR PDF:
1. Classic SNR — A-shape / V-shape from 2 OPPOSITE candles (buy+sell)
2. Open/Close SNR — from 2 SAME-direction candles (buy+buy | sell+sell)
3. Fresh until touched (wick = unfresh)
4. Body break → fresh again
5. Level usable max 2 times (F→UF, F→UF)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

import pandas as pd


class KeyLevelType(Enum):
    A_SHAPE = "A-shape"
    V_SHAPE = "V-shape"
    OPEN_CLOSE = "OC-shape"  # matches alert label "OC-shape KL"


@dataclass
class KeyLevel:
    level_type: KeyLevelType
    price: float
    candle_index: int
    timestamp: pd.Timestamp
    direction: str = ""          # buy | sell
    strength: float = 1.0
    source: str = ""
    is_fresh: bool = True
    touch_count: int = 0         # max 2 uses
    formed_at: Optional[pd.Timestamp] = None

    def __post_init__(self):
        if self.formed_at is None:
            self.formed_at = self.timestamp


def _aligned(a: float, b: float, tol: float) -> bool:
    if a == 0 or b == 0:
        return False
    return abs(a - b) / ((abs(a) + abs(b)) / 2) <= tol


def _is_bull(o: float, c: float) -> bool:
    return c > o


def _is_bear(o: float, c: float) -> bool:
    return c < o


def detect_a_shape(df: pd.DataFrame, tol: float = 0.0003, lookback: int = 60) -> List[KeyLevel]:
    """
    Classic A-shape (resistance / sell KL).
    Two OPPOSITE candles (buy+sell) whose opens (or close→open) align near the local high.
    """
    levels: List[KeyLevel] = []
    if len(df) < 4:
        return levels

    o = df["open"].values
    h = df["high"].values
    c = df["close"].values
    t = df.index
    start = max(1, len(df) - lookback)

    for i in range(start, len(df) - 1):
        bull_i = _is_bull(o[i], c[i])
        bear_i = _is_bear(o[i], c[i])
        bull_j = _is_bull(o[i + 1], c[i + 1])
        bear_j = _is_bear(o[i + 1], c[i + 1])

        # opposite direction required for classic SNR
        opposite = (bull_i and bear_j) or (bear_i and bull_j)
        if not opposite:
            continue

        candidates = []
        if _aligned(o[i], o[i + 1], tol):
            candidates.append(((o[i] + o[i + 1]) / 2, "aligned opens (A)"))
        if _aligned(c[i], o[i + 1], tol):
            candidates.append(((c[i] + o[i + 1]) / 2, "close→open (A)"))
        if _aligned(o[i], c[i + 1], tol):
            candidates.append(((o[i] + c[i + 1]) / 2, "open→close (A)"))

        peak = max(h[i], h[i + 1])
        for avg, src in candidates:
            # level must sit near the highs of the pair
            if abs(peak - avg) / max(abs(peak), 1e-9) <= 0.0025:
                levels.append(KeyLevel(
                    level_type=KeyLevelType.A_SHAPE,
                    price=float(avg),
                    candle_index=i,
                    timestamp=t[i],
                    direction="sell",
                    strength=1.35,
                    source=src,
                    formed_at=t[i],
                ))
    return levels


def detect_v_shape(df: pd.DataFrame, tol: float = 0.0003, lookback: int = 60) -> List[KeyLevel]:
    """
    Classic V-shape (support / buy KL).
    Two OPPOSITE candles whose opens (or close→open) align near the local low.
    """
    levels: List[KeyLevel] = []
    if len(df) < 4:
        return levels

    o = df["open"].values
    l = df["low"].values
    c = df["close"].values
    t = df.index
    start = max(1, len(df) - lookback)

    for i in range(start, len(df) - 1):
        bull_i = _is_bull(o[i], c[i])
        bear_i = _is_bear(o[i], c[i])
        bull_j = _is_bull(o[i + 1], c[i + 1])
        bear_j = _is_bear(o[i + 1], c[i + 1])

        opposite = (bull_i and bear_j) or (bear_i and bull_j)
        if not opposite:
            continue

        candidates = []
        if _aligned(o[i], o[i + 1], tol):
            candidates.append(((o[i] + o[i + 1]) / 2, "aligned opens (V)"))
        if _aligned(c[i], o[i + 1], tol):
            candidates.append(((c[i] + o[i + 1]) / 2, "close→open (V)"))
        if _aligned(o[i], c[i + 1], tol):
            candidates.append(((o[i] + c[i + 1]) / 2, "open→close (V)"))

        bottom = min(l[i], l[i + 1])
        for avg, src in candidates:
            if abs(avg - bottom) / max(abs(avg), 1e-9) <= 0.0025:
                levels.append(KeyLevel(
                    level_type=KeyLevelType.V_SHAPE,
                    price=float(avg),
                    candle_index=i,
                    timestamp=t[i],
                    direction="buy",
                    strength=1.35,
                    source=src,
                    formed_at=t[i],
                ))
    return levels


def detect_open_close(df: pd.DataFrame, tol: float = 0.0003, lookback: int = 60) -> List[KeyLevel]:
    """
    Open/Close SNR — 2 SAME-direction candles (buy+buy or sell+sell).
    Level at shared open/close alignment.
    """
    levels: List[KeyLevel] = []
    if len(df) < 4:
        return levels

    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    t = df.index
    start = max(1, len(df) - lookback)

    for i in range(start, len(df) - 1):
        same_bull = _is_bull(o[i], c[i]) and _is_bull(o[i + 1], c[i + 1])
        same_bear = _is_bear(o[i], c[i]) and _is_bear(o[i + 1], c[i + 1])
        if not (same_bull or same_bear):
            continue

        candidates = []
        if _aligned(o[i], o[i + 1], tol):
            candidates.append(((o[i] + o[i + 1]) / 2, "aligned opens (OC)"))
        if _aligned(c[i], c[i + 1], tol):
            candidates.append(((c[i] + c[i + 1]) / 2, "aligned closes (OC)"))
        if _aligned(c[i], o[i + 1], tol):
            candidates.append(((c[i] + o[i + 1]) / 2, "close→open (OC)"))
        if _aligned(o[i], c[i + 1], tol):
            candidates.append(((o[i] + c[i + 1]) / 2, "open→close (OC)"))

        peak = max(h[i], h[i + 1])
        bottom = min(l[i], l[i + 1])

        for avg, src in candidates:
            near_high = abs(peak - avg) / max(abs(peak), 1e-9) <= 0.003
            near_low = abs(avg - bottom) / max(abs(avg), 1e-9) <= 0.003
            if not (near_high or near_low):
                continue
            direction = "sell" if near_high and not near_low else ("buy" if near_low else ("sell" if same_bear else "buy"))
            levels.append(KeyLevel(
                level_type=KeyLevelType.OPEN_CLOSE,
                price=float(avg),
                candle_index=i,
                timestamp=t[i],
                direction=direction,
                strength=1.15,
                source=src,
                formed_at=t[i],
            ))
    return levels


def mark_freshness(levels: List[KeyLevel], df: pd.DataFrame) -> List[KeyLevel]:
    """
    Fresh / Unfresh rules (Malaysian SNR):
    - Fresh until touched
    - Wick touch → unfresh (counts as one use)
    - Body break beyond → becomes fresh again
    - Max 2 uses total
    """
    if not levels or df is None or len(df) < 2:
        return levels

    highs = df["high"].values
    lows = df["low"].values
    opens = df["open"].values
    closes = df["close"].values
    n = len(df)

    for kl in levels:
        touch_count = 0
        is_fresh = True
        start = kl.candle_index + 2  # after the pair that formed it

        for i in range(max(start, 0), n):
            hi = float(highs[i])
            lo = float(lows[i])
            op = float(opens[i])
            cl = float(closes[i])
            body_top = max(op, cl)
            body_bot = min(op, cl)
            px = kl.price

            # Body break through → fresh again
            if body_bot < px < body_top or (cl > px and op > px and lo < px) or (cl < px and op < px and hi > px):
                # clear body penetration
                if (cl > px and op < px) or (cl < px and op > px):
                    is_fresh = True
                    continue

            # Wick touch only
            wick_touch = (lo <= px <= hi) and not (body_bot <= px <= body_top)
            body_touch = body_bot <= px <= body_top

            if wick_touch or body_touch:
                if is_fresh:
                    touch_count += 1
                    is_fresh = False
                    if touch_count >= 2:
                        break

        kl.touch_count = touch_count
        kl.is_fresh = is_fresh and touch_count < 2

    return levels


def get_all_key_levels(df: pd.DataFrame, tol: float = 0.0003, lookback: int = 60) -> List[KeyLevel]:
    levels = (
        detect_a_shape(df, tol, lookback)
        + detect_v_shape(df, tol, lookback)
        + detect_open_close(df, tol, lookback)
    )
    levels = mark_freshness(levels, df)
    # Prefer usable levels (fresh or still under 2 touches)
    levels = [lv for lv in levels if lv.touch_count < 2]
    return levels


def closest_to_rejection(
    levels: List[KeyLevel],
    rej_high: float,
    rej_low: float,
    rej_close: float,
    direction: str,
    max_distance_pct: float = 0.012,
) -> Optional[Tuple[KeyLevel, float]]:
    """
    Closest KL to the rejection candle.
    Prefer: fresh → matching direction → A/V over OC → closer distance.
    """
    if not levels:
        return None

    ref = rej_high if direction == "SELL" else rej_low
    scored = []

    for lv in levels:
        dist = abs(lv.price - ref) / max(abs(ref), 1e-9)
        if dist > max_distance_pct:
            continue
        # also check close proximity
        dist_c = abs(lv.price - rej_close) / max(abs(rej_close), 1e-9)
        best_dist = min(dist, dist_c)

        score = best_dist
        if not lv.is_fresh:
            score += 0.002  # prefer fresh
        if lv.direction and lv.direction != direction.lower() and lv.direction != direction[:3].lower():
            # soft penalty if direction mismatches
            if (direction == "SELL" and lv.direction == "buy") or (direction == "BUY" and lv.direction == "sell"):
                score += 0.003
        if lv.level_type == KeyLevelType.OPEN_CLOSE:
            score += 0.0005  # slight preference for classic A/V
        if lv.level_type in (KeyLevelType.A_SHAPE, KeyLevelType.V_SHAPE):
            score -= 0.0003

        scored.append((score, lv, ref if dist <= dist_c else rej_close))

    if not scored:
        return None

    scored.sort(key=lambda x: x[0])
    _, kl, ref_px = scored[0]
    return kl, ref_px
