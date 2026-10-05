"""
Malaysian SNR Key Levels (strict)

Sources: Pitchou.FX PDF + MSNR community practice

1. A-level (resistance): opposite candles at a peak of the close path
   — bullish candle then bearish; level at the shared body edge (close→open)
2. V-level (support): opposite candles at a valley of the close path
   — bearish then bullish; level at shared body edge
3. Open/Close (gap): same-colour candles where close of 1 does not meet open of 2

Fresh / Unfresh:
- Fresh until wick-touched
- Wick touch → unfresh (1 use)
- Body close through → flip (RBS/SBR), can become fresh again
- Max 2 uses then discard
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple

import pandas as pd


class KeyLevelType(Enum):
    A_SHAPE = "A-shape"
    V_SHAPE = "V-shape"
    OPEN_CLOSE = "OC-shape"


@dataclass
class KeyLevel:
    level_type: KeyLevelType
    price: float
    candle_index: int
    timestamp: pd.Timestamp
    direction: str = ""  # sell | buy
    strength: float = 1.0
    source: str = ""
    is_fresh: bool = True
    touch_count: int = 0
    formed_at: Optional[pd.Timestamp] = None
    price_high: Optional[float] = None  # for gap zones
    price_low: Optional[float] = None

    def __post_init__(self):
        if self.formed_at is None:
            self.formed_at = self.timestamp
        if self.price_high is None:
            self.price_high = self.price
        if self.price_low is None:
            self.price_low = self.price


def _is_bull(o: float, c: float) -> bool:
    return c > o


def _is_bear(o: float, c: float) -> bool:
    return c < o


def _near(a: float, b: float, tol: float) -> bool:
    if a == 0 and b == 0:
        return True
    mid = (abs(a) + abs(b)) / 2 or 1e-9
    return abs(a - b) / mid <= tol


def detect_a_shape(df: pd.DataFrame, tol: float = 0.0004, lookback: int = 80) -> List[KeyLevel]:
    """
    A-shape resistance: bullish candle followed by bearish (opposite).
    Level = peak of the close-to-close path ≈ max(c0, o1) or aligned body edge.
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
        # opposite: bull then bear OR bear then bull at a peak
        bull0, bear0 = _is_bull(o[i], c[i]), _is_bear(o[i], c[i])
        bull1, bear1 = _is_bull(o[i + 1], c[i + 1]), _is_bear(o[i + 1], c[i + 1])
        if not ((bull0 and bear1) or (bear0 and bull1)):
            continue

        # classic body join: close of first meets open of second
        candidates = []
        if _near(c[i], o[i + 1], tol):
            px = (float(c[i]) + float(o[i + 1])) / 2
            candidates.append((px, "close→open (A)"))
        if _near(o[i], o[i + 1], tol):
            px = (float(o[i]) + float(o[i + 1])) / 2
            candidates.append((px, "aligned opens (A)"))
        # peak of closes (line-chart style)
        peak_close = max(float(c[i]), float(c[i + 1]))
        if not candidates:
            # still form A if bodies form a clear peak vs neighbours
            candidates.append((peak_close, "close peak (A)"))

        peak_wick = max(float(h[i]), float(h[i + 1]))
        for px, src in candidates:
            # must sit near the highs of the pair (resistance)
            if abs(peak_wick - px) / max(abs(peak_wick), 1e-9) > 0.004:
                # allow slightly lower body level if still upper half of range
                body_top = max(float(o[i]), float(c[i]), float(o[i + 1]), float(c[i + 1]))
                if abs(body_top - px) / max(abs(body_top), 1e-9) > 0.003:
                    continue
            levels.append(
                KeyLevel(
                    KeyLevelType.A_SHAPE,
                    float(px),
                    i,
                    t[i],
                    direction="sell",
                    strength=1.4,
                    source=src,
                    formed_at=t[i],
                )
            )
    return levels


def detect_v_shape(df: pd.DataFrame, tol: float = 0.0004, lookback: int = 80) -> List[KeyLevel]:
    """
    V-shape support: bearish then bullish (opposite) at a valley.
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
        bull0, bear0 = _is_bull(o[i], c[i]), _is_bear(o[i], c[i])
        bull1, bear1 = _is_bull(o[i + 1], c[i + 1]), _is_bear(o[i + 1], c[i + 1])
        if not ((bull0 and bear1) or (bear0 and bull1)):
            continue

        candidates = []
        if _near(c[i], o[i + 1], tol):
            px = (float(c[i]) + float(o[i + 1])) / 2
            candidates.append((px, "close→open (V)"))
        if _near(o[i], o[i + 1], tol):
            px = (float(o[i]) + float(o[i + 1])) / 2
            candidates.append((px, "aligned opens (V)"))
        valley_close = min(float(c[i]), float(c[i + 1]))
        if not candidates:
            candidates.append((valley_close, "close valley (V)"))

        bottom_wick = min(float(l[i]), float(l[i + 1]))
        for px, src in candidates:
            if abs(px - bottom_wick) / max(abs(px), 1e-9) > 0.004:
                body_bot = min(float(o[i]), float(c[i]), float(o[i + 1]), float(c[i + 1]))
                if abs(px - body_bot) / max(abs(px), 1e-9) > 0.003:
                    continue
            levels.append(
                KeyLevel(
                    KeyLevelType.V_SHAPE,
                    float(px),
                    i,
                    t[i],
                    direction="buy",
                    strength=1.4,
                    source=src,
                    formed_at=t[i],
                )
            )
    return levels


def detect_open_close(df: pd.DataFrame, tol: float = 0.0004, lookback: int = 80) -> List[KeyLevel]:
    """
    OC / gap: two SAME-colour candles.
    If close of first does not meet open of second → gap zone.
    If they meet → single OC level.
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

        c0, o1 = float(c[i]), float(o[i + 1])
        # gap if they don't meet
        gap = not _near(c0, o1, tol)
        if gap:
            lo, hi = min(c0, o1), max(c0, o1)
            px = (lo + hi) / 2
            src = "gap OC"
        else:
            lo = hi = px = (c0 + o1) / 2
            src = "close→open (OC)"

        # also aligned opens / closes
        extras = []
        if _near(float(o[i]), float(o[i + 1]), tol):
            extras.append(((float(o[i]) + float(o[i + 1])) / 2, "aligned opens (OC)"))
        if _near(float(c[i]), float(c[i + 1]), tol):
            extras.append(((float(c[i]) + float(c[i + 1])) / 2, "aligned closes (OC)"))

        peak = max(float(h[i]), float(h[i + 1]))
        bottom = min(float(l[i]), float(l[i + 1]))
        near_high = abs(peak - px) / max(abs(peak), 1e-9) <= 0.004
        near_low = abs(px - bottom) / max(abs(px), 1e-9) <= 0.004
        if not (near_high or near_low or gap):
            continue

        direction = "sell" if (near_high and not near_low) or same_bear else "buy"
        levels.append(
            KeyLevel(
                KeyLevelType.OPEN_CLOSE,
                float(px),
                i,
                t[i],
                direction=direction,
                strength=1.15,
                source=src,
                formed_at=t[i],
                price_high=float(hi),
                price_low=float(lo),
            )
        )
        for epx, esrc in extras:
            levels.append(
                KeyLevel(
                    KeyLevelType.OPEN_CLOSE,
                    float(epx),
                    i,
                    t[i],
                    direction=direction,
                    strength=1.05,
                    source=esrc,
                    formed_at=t[i],
                )
            )
    return levels


def mark_freshness(levels: List[KeyLevel], df: pd.DataFrame) -> List[KeyLevel]:
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
        start = kl.candle_index + 2

        for i in range(max(start, 0), n):
            hi, lo = float(highs[i]), float(lows[i])
            op, cl = float(opens[i]), float(closes[i])
            body_top, body_bot = max(op, cl), min(op, cl)
            px = kl.price

            # body closed through → flip, fresh again
            if (cl > px and op > px and lo < px) or (cl < px and op < px and hi > px):
                if body_bot < px < body_top or (cl - px) * (op - px) < 0:
                    is_fresh = True
                    continue
            # clear body break
            if body_bot > px and lo <= px:
                pass
            if (cl > px and op < px) or (cl < px and op > px):
                is_fresh = True
                continue

            wick_only = (lo <= px <= hi) and not (body_bot <= px <= body_top)
            body_touch = body_bot <= px <= body_top

            if wick_only or body_touch:
                if is_fresh:
                    touch_count += 1
                    is_fresh = False
                    if touch_count >= 2:
                        break

        kl.touch_count = touch_count
        kl.is_fresh = is_fresh and touch_count < 2

    return levels


def get_all_key_levels(df: pd.DataFrame, tol: float = 0.0004, lookback: int = 80) -> List[KeyLevel]:
    levels = (
        detect_a_shape(df, tol, lookback)
        + detect_v_shape(df, tol, lookback)
        + detect_open_close(df, tol, lookback)
    )
    levels = mark_freshness(levels, df)
    return [lv for lv in levels if lv.touch_count < 2]


def find_rejection_at_kl(
    df: pd.DataFrame,
    levels: List[KeyLevel],
    lookback_bars: int = 4,
    max_distance_pct: float = 0.006,
) -> Optional[dict]:
    """
    Find a recent HTF candle that:
    - Wicks into a named KL
    - Body closes back (rejection, not break)
    Returns direction, kl, candle data.
    """
    if df is None or len(df) < 3 or not levels:
        return None

    n = len(df)
    start = max(1, n - lookback_bars)

    best = None
    best_score = 999.0

    for i in range(n - 1, start - 1, -1):
        o = float(df["open"].iloc[i])
        h = float(df["high"].iloc[i])
        l = float(df["low"].iloc[i])
        c = float(df["close"].iloc[i])
        body_top, body_bot = max(o, c), min(o, c)
        full = max(h - l, 1e-12)
        upper = h - body_top
        lower = body_bot - l

        for kl in levels:
            # level must exist before or at this candle
            if kl.candle_index >= i:
                continue
            px = kl.price
            dist_h = abs(h - px) / max(abs(px), 1e-9)
            dist_l = abs(l - px) / max(abs(px), 1e-9)

            # SELL rejection: wick up into KL (near high), close back below level
            if dist_h <= max_distance_pct and h >= px * 0.9995:
                if c < px or (upper / full >= 0.15 and c <= body_top):
                    # body did not close above as a break
                    if c > px and body_bot > px:
                        continue  # clear break up — not rejection
                    score = dist_h
                    if not kl.is_fresh:
                        score += 0.002
                    if kl.direction == "buy":
                        score += 0.001
                    if score < best_score:
                        best_score = score
                        best = {
                            "direction": "SELL",
                            "kl": kl,
                            "index": i,
                            "open": o,
                            "high": h,
                            "low": l,
                            "close": c,
                            "time": df.index[i],
                            "ref_price": px,
                        }

            # BUY rejection: wick down into KL, close back above
            if dist_l <= max_distance_pct and l <= px * 1.0005:
                if c > px or (lower / full >= 0.15 and c >= body_bot):
                    if c < px and body_top < px:
                        continue  # clear break down
                    score = dist_l
                    if not kl.is_fresh:
                        score += 0.002
                    if kl.direction == "sell":
                        score += 0.001
                    if score < best_score:
                        best_score = score
                        best = {
                            "direction": "BUY",
                            "kl": kl,
                            "index": i,
                            "open": o,
                            "high": h,
                            "low": l,
                            "close": c,
                            "time": df.index[i],
                            "ref_price": px,
                        }

    return best


def closest_to_rejection(
    levels: List[KeyLevel],
    rej_high: float,
    rej_low: float,
    rej_close: float,
    direction: str,
    max_distance_pct: float = 0.012,
) -> Optional[Tuple[KeyLevel, float]]:
    if not levels:
        return None
    ref = rej_high if direction == "SELL" else rej_low
    scored = []
    for lv in levels:
        dist = abs(lv.price - ref) / max(abs(ref), 1e-9)
        if dist > max_distance_pct:
            continue
        dist_c = abs(lv.price - rej_close) / max(abs(rej_close), 1e-9)
        best_d = min(dist, dist_c)
        score = best_d
        if not lv.is_fresh:
            score += 0.002
        if lv.level_type == KeyLevelType.OPEN_CLOSE:
            score += 0.0004
        scored.append((score, lv, ref if dist <= dist_c else rej_close))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0])
    _, kl, ref_px = scored[0]
    return kl, ref_px
