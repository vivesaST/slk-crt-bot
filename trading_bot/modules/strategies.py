"""
Three independent strategies:
1. SLK  — Daily rejection at Key Level + 4H External BO
2. Daily CRT — C1 range / C2 sweep, alert 5 min before Daily close
3. 4H CRT — C1 form / C2 sweep, alert 5 min before 4H C2 close
"""
from dataclasses import dataclass
from typing import Optional, List
from datetime import timedelta

import pandas as pd

import config
from modules.structure import determine_trend, detect_external_break, Trend
from modules.key_levels import get_key_levels, nearest_kl, KeyLevelType
from modules.utils import format_price, format_dt, display_symbol, minutes_until_candle_close, now_ny


@dataclass
class AlertSignal:
    strategy: str  # SLK | DAILY_CRT | H4_CRT
    pair: str
    direction: str
    message: str
    score: float = 1.0


# ---------- SLK ----------
def scan_slk(pair: str, df_daily: pd.DataFrame, df_4h: pd.DataFrame) -> Optional[AlertSignal]:
    if df_daily is None or df_4h is None or len(df_4h) < 30 or len(df_daily) < 10:
        return None

    daily_trend = determine_trend(df_daily, 15)
    ext = detect_external_break(df_4h)
    if ext is None:
        return None

    if daily_trend == Trend.BULLISH and ext.direction != "bullish":
        return None
    if daily_trend == Trend.BEARISH and ext.direction != "bearish":
        return None

    direction = "BUY" if ext.direction == "bullish" else "SELL"
    levels = get_key_levels(df_4h, config.OPEN_TOLERANCE, config.KEY_LEVEL_LOOKBACK)
    price = float(df_4h["close"].iloc[-1])

    preferred = None
    for kl in levels:
        if direction == "SELL" and kl.level_type == KeyLevelType.A_SHAPE:
            if abs(kl.price - price) / price < 0.006:
                preferred = kl
                break
        if direction == "BUY" and kl.level_type == KeyLevelType.V_SHAPE:
            if abs(kl.price - price) / price < 0.006:
                preferred = kl
                break
    kl = preferred or nearest_kl(levels, price)
    if kl is None:
        return None

    disp = display_symbol(pair)
    msg = (
        f"🚨 SLK · {direction} · {disp} · D1→H4\n"
        f"External breakout confirmed\n\n"
        f"Rejected at {kl.level_type.value} KL @ {format_price(kl.price, pair)}.\n\n"
        f"External BO @ {format_price(ext.break_price, pair)} · {format_dt(ext.break_time.to_pydatetime() if hasattr(ext.break_time, 'to_pydatetime') else ext.break_time)}\n"
        f"{'Trend aligned with D1' if daily_trend != Trend.NEUTRAL else 'Daily trend neutral'}\n\n"
        f"⚠️ Not an entry signal. Bias only — wait for your entry model."
    )
    score = 1.5 + (0.4 if kl.has_history else 0) + (0.3 if daily_trend != Trend.NEUTRAL else 0)
    return AlertSignal("SLK", pair, direction, msg, score)


# ---------- Daily CRT ----------
def _daily_crt_setup(df: pd.DataFrame) -> Optional[dict]:
    """
    Monday creates high/low range.
    Tue/Wed sweep → bias for distribution (Thu/Fri).
    Returns dict with direction, mon_high, mon_low, sweep_info or None.
    """
    if df is None or len(df) < 5:
        return None
    # walk back for most recent Monday
    for i in range(len(df) - 1, max(len(df) - 12, -1), -1):
        if df.index[i].weekday() != 0:
            continue
        mon_high = float(df["high"].iloc[i])
        mon_low = float(df["low"].iloc[i])
        direction = None
        sweep_day = None
        for j in range(i + 1, min(i + 5, len(df))):
            wd = df.index[j].weekday()
            if wd not in (1, 2, 3, 4):  # Tue–Fri
                continue
            h, l = float(df["high"].iloc[j]), float(df["low"].iloc[j])
            # sweep high only → sell bias
            if h > mon_high and l >= mon_low * 0.999:
                direction = "SELL"
                sweep_day = j
            # sweep low only → buy bias
            elif l < mon_low and h <= mon_high * 1.001:
                direction = "BUY"
                sweep_day = j
            elif h > mon_high and l < mon_low:
                c = float(df["close"].iloc[j])
                direction = "BUY" if c > (mon_high + mon_low) / 2 else "SELL"
                sweep_day = j
        if direction:
            return {
                "direction": direction,
                "mon_high": mon_high,
                "mon_low": mon_low,
                "monday_idx": i,
                "sweep_idx": sweep_day,
            }
        break
    return None


def scan_daily_crt(pair: str, df_daily: pd.DataFrame) -> Optional[AlertSignal]:
    """Alert when Daily CRT is valid AND within CRT_ALERT_MINUTES_BEFORE_CLOSE of daily close."""
    if df_daily is None or len(df_daily) < 5:
        return None

    setup = _daily_crt_setup(df_daily)
    if not setup:
        return None

    # Current (possibly incomplete) daily candle
    last = df_daily.iloc[-1]
    last_ts = df_daily.index[-1]
    remaining = minutes_until_candle_close(last_ts.to_pydatetime(), "D")

    # Only fire inside the 5-minute window (and not after close)
    window = config.CRT_ALERT_MINUTES_BEFORE_CLOSE
    if remaining < 0 or remaining > window + 0.5:
        return None

    disp = display_symbol(pair)
    direction = setup["direction"]
    msg = (
        f"🕯 DAILY CRT · {direction} · {disp}\n"
        f"~{int(max(remaining, 0))} min to Daily close\n\n"
        f"Monday range: {format_price(setup['mon_high'], pair)} – {format_price(setup['mon_low'], pair)}\n"
        f"Sweep bias: {direction}\n"
        f"Prepare for C3 expansion after close.\n\n"
        f"⚠️ Bias only — use your entry model on lower TF."
    )
    return AlertSignal("DAILY_CRT", pair, direction, msg, 2.0)


# ---------- 4H CRT ----------
def _h4_crt_c1_c2(df: pd.DataFrame) -> Optional[dict]:
    """
    C1 = previous completed 4H candle (range).
    C2 = current incomplete 4H candle that has swept C1 high or low.
    """
    if df is None or len(df) < 3:
        return None

    # Prefer last incomplete as C2, previous complete as C1
    # If last is complete, no live C2
    last_complete = bool(df["complete"].iloc[-1]) if "complete" in df.columns else True
    if last_complete:
        # still allow if we are near close of last candle treated as C2
        c2 = df.iloc[-1]
        c1 = df.iloc[-2]
        c2_idx = len(df) - 1
    else:
        c2 = df.iloc[-1]
        c1 = df.iloc[-2]
        c2_idx = len(df) - 1

    c1_high, c1_low = float(c1["high"]), float(c1["low"])
    c2_high, c2_low = float(c2["high"]), float(c2["low"])
    c2_close = float(c2["close"])

    swept_high = c2_high > c1_high
    swept_low = c2_low < c1_low

    if not swept_high and not swept_low:
        return None

    if swept_high and not swept_low:
        direction = "SELL"  # liquidity above taken → look for expansion down
    elif swept_low and not swept_high:
        direction = "BUY"
    else:
        # both swept — bias from close vs mid
        mid = (c1_high + c1_low) / 2
        direction = "BUY" if c2_close > mid else "SELL"

    return {
        "direction": direction,
        "c1_high": c1_high,
        "c1_low": c1_low,
        "c2_time": df.index[c2_idx],
        "swept_high": swept_high,
        "swept_low": swept_low,
    }


def scan_h4_crt(pair: str, df_4h: pd.DataFrame) -> Optional[AlertSignal]:
    """Alert 5 min before 4H C2 closes when C2 has swept C1."""
    if df_4h is None or len(df_4h) < 3:
        return None

    setup = _h4_crt_c1_c2(df_4h)
    if not setup:
        return None

    c2_ts = setup["c2_time"]
    remaining = minutes_until_candle_close(c2_ts.to_pydatetime(), "H4")
    window = config.CRT_ALERT_MINUTES_BEFORE_CLOSE
    if remaining < 0 or remaining > window + 0.5:
        return None

    disp = display_symbol(pair)
    direction = setup["direction"]
    sweep_txt = []
    if setup["swept_high"]:
        sweep_txt.append("swept C1 high")
    if setup["swept_low"]:
        sweep_txt.append("swept C1 low")
    msg = (
        f"🕯 4H CRT · {direction} · {disp}\n"
        f"~{int(max(remaining, 0))} min to C2 close\n\n"
        f"C1 range: {format_price(setup['c1_high'], pair)} – {format_price(setup['c1_low'], pair)}\n"
        f"C2: {', '.join(sweep_txt)}\n"
        f"Prepare entry for C3 expansion.\n\n"
        f"⚠️ Bias only — drop to 15m for CISD/OB entry."
    )
    return AlertSignal("H4_CRT", pair, direction, msg, 2.0)


def run_all_strategies(
    pair: str,
    df_daily: pd.DataFrame,
    df_4h: pd.DataFrame,
    enable_slk: bool,
    enable_daily_crt: bool,
    enable_h4_crt: bool,
) -> List[AlertSignal]:
    signals = []
    if enable_slk:
        s = scan_slk(pair, df_daily, df_4h)
        if s:
            signals.append(s)
    if enable_daily_crt:
        s = scan_daily_crt(pair, df_daily)
        if s:
            signals.append(s)
    if enable_h4_crt:
        s = scan_h4_crt(pair, df_4h)
        if s:
            signals.append(s)
    return signals
