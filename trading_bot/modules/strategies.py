"""
Three independent strategies:
1. SLK  — Daily rejection at closest KL + proper 4H External BO
2. Daily CRT — Monday range / sweep
3. 4H CRT — C1 range / C2 sweep
"""
from dataclasses import dataclass
from typing import Optional, List

import pandas as pd

import config
from modules.structure import determine_trend, detect_external_break, detect_snr_breakout, Trend
from modules.key_levels import get_all_key_levels, closest_to_rejection, KeyLevelType
from modules.utils import format_price, format_dt, display_symbol, minutes_until_candle_close


@dataclass
class AlertSignal:
    strategy: str
    pair: str
    direction: str
    message: str
    score: float = 1.0


def scan_slk(pair: str, df_daily: pd.DataFrame, df_4h: pd.DataFrame) -> Optional[AlertSignal]:
    """
    Daily SLK storyline (Malaysian SNR):
    1. Daily rejection at fresh SNR (A / V / OC)
    2. Optional: sweep of previous daily candle high/low + close back
    3. 4H EXTERNAL body breakout (level created BEFORE rejection)
    4. Alert format matches Malaysian SNR style
    """
    if df_daily is None or df_4h is None or len(df_4h) < 30 or len(df_daily) < 10:
        return None

    levels_d = get_all_key_levels(df_daily, config.OPEN_TOLERANCE, 60)
    if not levels_d:
        return None

    rej = None
    direction = None
    sweep_txt = ""

    for i in range(len(df_daily) - 1, max(len(df_daily) - 5, -1), -1):
        row = df_daily.iloc[i]
        o = float(row["open"])
        h = float(row["high"])
        l = float(row["low"])
        c = float(row["close"])
        body = abs(c - o)
        upper = h - max(o, c)
        lower = min(o, c) - l
        full = max(h - l, 1e-12)

        # previous candle for sweep description
        if i > 0:
            prev_h = float(df_daily["high"].iloc[i - 1])
            prev_l = float(df_daily["low"].iloc[i - 1])
        else:
            prev_h = prev_l = None

        # SELL rejection (wick up, close back)
        if upper >= body * 0.4 and upper / full >= 0.20:
            found = closest_to_rejection(levels_d, h, l, c, "SELL")
            if found:
                rej = {"i": i, "high": h, "low": l, "close": c, "time": df_daily.index[i], "open": o}
                direction = "SELL"
                if prev_h is not None and h > prev_h and c < prev_h:
                    sweep_txt = f"Swept previous candle high {format_price(prev_h, pair)}, closed back below; "
                elif prev_h is not None and h >= prev_h * 0.999:
                    sweep_txt = f"Tapped previous candle high {format_price(prev_h, pair)}; "
                break

        # BUY rejection (wick down, close back)
        if lower >= body * 0.4 and lower / full >= 0.20:
            found = closest_to_rejection(levels_d, h, l, c, "BUY")
            if found:
                rej = {"i": i, "high": h, "low": l, "close": c, "time": df_daily.index[i], "open": o}
                direction = "BUY"
                if prev_l is not None and l < prev_l and c > prev_l:
                    sweep_txt = f"Swept previous candle low {format_price(prev_l, pair)}, closed back above; "
                elif prev_l is not None and l <= prev_l * 1.001:
                    sweep_txt = f"Tapped previous candle low {format_price(prev_l, pair)}; "
                break

    if rej is None or direction is None:
        return None

    rej_time = rej["time"]
    if hasattr(rej_time, "to_pydatetime"):
        rej_time_py = rej_time.to_pydatetime()
    else:
        rej_time_py = rej_time

    ext = detect_snr_breakout(
        df_4h,
        direction=direction,
        rejection_time=rej_time_py,
        max_age_bars=12,
    )
    if ext is None:
        return None

    levels = get_all_key_levels(df_daily, config.OPEN_TOLERANCE, 60)
    levels += get_all_key_levels(df_4h, config.OPEN_TOLERANCE, 40)
    found = closest_to_rejection(levels, rej["high"], rej["low"], rej["close"], direction)
    if found is None:
        return None
    kl, ref_px = found

    # Prefer fresh KL in description
    fresh_tag = "fresh " if kl.is_fresh else ""
    kl_label = kl.level_type.value  # A-shape | V-shape | OC-shape

    daily_trend = determine_trend(df_daily, 15)
    disp = display_symbol(pair)

    bt = ext.break_time
    if hasattr(bt, "to_pydatetime"):
        bt = bt.to_pydatetime()
    rt = rej["time"]
    if hasattr(rt, "to_pydatetime"):
        rt = rt.to_pydatetime()

    formed = kl.formed_at or kl.timestamp
    if hasattr(formed, "to_pydatetime"):
        formed = formed.to_pydatetime()

    trend_txt = "Trend aligned with D1" if daily_trend != Trend.NEUTRAL else "Daily trend neutral"
    if daily_trend != Trend.NEUTRAL:
        if (direction == "BUY" and daily_trend == Trend.BULLISH) or (
            direction == "SELL" and daily_trend == Trend.BEARISH
        ):
            trend_txt = "Trend aligned with D1"
        else:
            trend_txt = "Trend counter to D1"

    # Next Day Rule: BO candle date is after rejection date (or same session next bar)
    next_day = False
    try:
        if bt.date() > rt.date():
            next_day = True
        elif bt.date() == rt.date() and getattr(bt, "hour", 0) >= 12 and getattr(rt, "hour", 0) < 12:
            next_day = True
    except Exception:
        next_day = False
    next_day_line = "✅ Next Day Rule" if next_day else "⬜ Same-session BO"

    emoji = "🔴" if direction == "SELL" else "🟢"

    msg = (
        f"{emoji} {direction} · {disp} · D1→H4\n"
        f"External breakout confirmed\n\n"
        f"{sweep_txt}rejected {fresh_tag}{kl_label} KL @ {format_price(kl.price, pair)}.\n\n"
        f"External BO @ {format_price(ext.break_price, pair)} · {format_dt(bt)}\n"
        f"Rejected on {format_dt(rt)}\n"
        f"Key level {format_price(kl.price, pair)} · formed {format_dt(formed)}\n"
        f"{trend_txt}\n"
        f"{next_day_line}\n\n"
        f"⚠️ Not an entry signal. Bias only — wait for your entry model."
    )

    score = 1.5
    if kl.level_type in (KeyLevelType.A_SHAPE, KeyLevelType.V_SHAPE):
        score += 0.3
    if kl.is_fresh:
        score += 0.2
    if next_day:
        score += 0.15
    if daily_trend != Trend.NEUTRAL and (
        (direction == "BUY" and daily_trend == Trend.BULLISH)
        or (direction == "SELL" and daily_trend == Trend.BEARISH)
    ):
        score += 0.25

    return AlertSignal("SLK", pair, direction, msg, score)


def _daily_crt_setup(df: pd.DataFrame) -> Optional[dict]:
    if df is None or len(df) < 5:
        return None
    for i in range(len(df) - 1, max(len(df) - 12, -1), -1):
        if df.index[i].weekday() != 0:
            continue
        mon_high = float(df["high"].iloc[i])
        mon_low = float(df["low"].iloc[i])
        direction = None
        for j in range(i + 1, min(i + 5, len(df))):
            if df.index[j].weekday() not in (1, 2, 3, 4):
                continue
            h, l = float(df["high"].iloc[j]), float(df["low"].iloc[j])
            if h > mon_high and l >= mon_low * 0.999:
                direction = "SELL"
            elif l < mon_low and h <= mon_high * 1.001:
                direction = "BUY"
            elif h > mon_high and l < mon_low:
                c = float(df["close"].iloc[j])
                direction = "BUY" if c > (mon_high + mon_low) / 2 else "SELL"
        if direction:
            return {"direction": direction, "mon_high": mon_high, "mon_low": mon_low}
        break
    return None


def scan_daily_crt(pair: str, df_daily: pd.DataFrame) -> Optional[AlertSignal]:
    if df_daily is None or len(df_daily) < 5:
        return None
    setup = _daily_crt_setup(df_daily)
    if not setup:
        return None
    last_ts = df_daily.index[-1]
    remaining = minutes_until_candle_close(last_ts.to_pydatetime(), "D")
    if remaining < 0:
        return None
    near_close = remaining <= config.CRT_ALERT_MINUTES_BEFORE_CLOSE + 0.5
    disp = display_symbol(pair)
    direction = setup["direction"]
    timing = (
        f"~{int(remaining)} min to Daily close"
        if near_close
        else f"Daily still open (~{int(remaining)} min left)"
    )
    msg = (
        f"🕯 DAILY CRT · {direction} · {disp}\n"
        f"{timing}\n\n"
        f"Monday range: {format_price(setup['mon_high'], pair)} – {format_price(setup['mon_low'], pair)}\n"
        f"Sweep bias: {direction}\n"
        f"Prepare for C3 expansion.\n\n"
        f"⚠️ Bias only — use your entry model on lower TF."
    )
    return AlertSignal("DAILY_CRT", pair, direction, msg, 2.0 if near_close else 1.6)


def _h4_crt_c1_c2(df: pd.DataFrame) -> Optional[dict]:
    if df is None or len(df) < 3:
        return None
    c2 = df.iloc[-1]
    c1 = df.iloc[-2]
    c1_high, c1_low = float(c1["high"]), float(c1["low"])
    c2_high, c2_low = float(c2["high"]), float(c2["low"])
    c2_close = float(c2["close"])
    swept_high = c2_high > c1_high
    swept_low = c2_low < c1_low
    if not swept_high and not swept_low:
        return None
    if swept_high and not swept_low:
        direction = "SELL"
    elif swept_low and not swept_high:
        direction = "BUY"
    else:
        mid = (c1_high + c1_low) / 2
        direction = "BUY" if c2_close > mid else "SELL"
    return {
        "direction": direction,
        "c1_high": c1_high,
        "c1_low": c1_low,
        "c2_time": df.index[-1],
        "swept_high": swept_high,
        "swept_low": swept_low,
    }


def scan_h4_crt(pair: str, df_4h: pd.DataFrame) -> Optional[AlertSignal]:
    if df_4h is None or len(df_4h) < 3:
        return None
    setup = _h4_crt_c1_c2(df_4h)
    if not setup:
        return None
    remaining = minutes_until_candle_close(setup["c2_time"].to_pydatetime(), "H4")
    if remaining < 0:
        return None
    near_close = remaining <= config.CRT_ALERT_MINUTES_BEFORE_CLOSE + 0.5
    disp = display_symbol(pair)
    direction = setup["direction"]
    sweep_txt = []
    if setup["swept_high"]:
        sweep_txt.append("swept C1 high")
    if setup["swept_low"]:
        sweep_txt.append("swept C1 low")
    timing = (
        f"~{int(remaining)} min to C2 close"
        if near_close
        else f"C2 open (~{int(remaining)} min left)"
    )
    msg = (
        f"🕯 4H CRT · {direction} · {disp}\n"
        f"{timing}\n\n"
        f"C1 range: {format_price(setup['c1_high'], pair)} – {format_price(setup['c1_low'], pair)}\n"
        f"C2: {', '.join(sweep_txt)}\n"
        f"Prepare entry for C3 expansion.\n\n"
        f"⚠️ Bias only — drop to 15m for CISD/OB entry."
    )
    return AlertSignal("H4_CRT", pair, direction, msg, 2.0 if near_close else 1.6)




def _htf_rejection_or_sweep(df: pd.DataFrame, lookback: int = 3) -> Optional[dict]:
    """
    Higher-TF event:
    - Rejection wick on a recent candle, OR
    - Sweep of previous completed candle high/low
    Returns direction BUY/SELL and rejection reference prices.
    """
    if df is None or len(df) < 4:
        return None

    # Prefer last incomplete as current; use previous completes for structure
    n = len(df)
    # Scan last `lookback` bars for rejection or sweep vs prior bar
    for i in range(n - 1, max(n - lookback - 1, 0), -1):
        row = df.iloc[i]
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        body = abs(c - o)
        upper = h - max(o, c)
        lower = min(o, c) - l
        full = max(h - l, 1e-12)

        # Sweep of previous candle high/low
        if i >= 1:
            prev = df.iloc[i - 1]
            ph, pl = float(prev["high"]), float(prev["low"])
            if h > ph and l >= pl * 0.9995:
                # swept high only → sell bias
                return {
                    "direction": "SELL",
                    "high": h, "low": l, "close": c,
                    "time": df.index[i],
                    "event": "sweep_high",
                    "idx": i,
                }
            if l < pl and h <= ph * 1.0005:
                return {
                    "direction": "BUY",
                    "high": h, "low": l, "close": c,
                    "time": df.index[i],
                    "event": "sweep_low",
                    "idx": i,
                }
            if h > ph and l < pl:
                mid = (ph + pl) / 2
                return {
                    "direction": "BUY" if c > mid else "SELL",
                    "high": h, "low": l, "close": c,
                    "time": df.index[i],
                    "event": "sweep_both",
                    "idx": i,
                }

        # Rejection wick
        if upper >= body * 0.5 and upper / full >= 0.25:
            return {
                "direction": "SELL",
                "high": h, "low": l, "close": c,
                "time": df.index[i],
                "event": "rejection_high",
                "idx": i,
            }
        if lower >= body * 0.5 and lower / full >= 0.25:
            return {
                "direction": "BUY",
                "high": h, "low": l, "close": c,
                "time": df.index[i],
                "event": "rejection_low",
                "idx": i,
            }
    return None


def _scan_htf_slk(
    pair: str,
    df_htf: pd.DataFrame,
    df_ltf: pd.DataFrame,
    strategy_id: str,
    htf_label: str,
    ltf_label: str,
    bo_max_age: int = 3,
) -> Optional[AlertSignal]:
    """
    Generic SLK:
    HTF rejection or sweep of previous HTF high/low
    + LTF (one TF lower) fresh external BO in same direction
    + closest KL to HTF rejection/sweep
    """
    if df_htf is None or df_ltf is None or len(df_htf) < 5 or len(df_ltf) < 25:
        return None

    htf_event = _htf_rejection_or_sweep(df_htf, lookback=3)
    if htf_event is None:
        return None

    direction = htf_event["direction"]
    ext = detect_external_break(df_ltf, max_age_bars=bo_max_age)
    if ext is None:
        return None

    # BO must agree with HTF bias
    if direction == "BUY" and ext.direction != "bullish":
        return None
    if direction == "SELL" and ext.direction != "bearish":
        return None

    levels = get_all_key_levels(df_htf, config.OPEN_TOLERANCE, 30)
    levels += get_all_key_levels(df_ltf, config.OPEN_TOLERANCE, 40)
    found = closest_to_rejection(
        levels, htf_event["high"], htf_event["low"], htf_event["close"], direction
    )
    if found is None:
        return None
    kl, ref_px = found

    disp = display_symbol(pair)
    bt = ext.break_time
    if hasattr(bt, "to_pydatetime"):
        bt = bt.to_pydatetime()
    rt = htf_event["time"]
    if hasattr(rt, "to_pydatetime"):
        rt = rt.to_pydatetime()

    event_txt = htf_event["event"].replace("_", " ")
    fresh_tag = "fresh " if getattr(kl, "is_fresh", True) else ""
    kl_label = kl.level_type.value
    formed = getattr(kl, "formed_at", None) or kl.timestamp
    if hasattr(formed, "to_pydatetime"):
        formed = formed.to_pydatetime()

    next_day = False
    try:
        if bt.date() > rt.date():
            next_day = True
    except Exception:
        pass
    next_day_line = "✅ Next Day Rule" if next_day else "⬜ Same-session BO"
    emoji = "🔴" if direction == "SELL" else "🟢"

    msg = (
        f"{emoji} {direction} · {disp} · {htf_label}→{ltf_label}\n"
        f"External breakout confirmed\n\n"
        f"{htf_label} {event_txt}; rejected {fresh_tag}{kl_label} KL @ {format_price(kl.price, pair)}.\n\n"
        f"External BO @ {format_price(ext.break_price, pair)} · {format_dt(bt)}\n"
        f"Rejected on {format_dt(rt)}\n"
        f"Key level {format_price(kl.price, pair)} · formed {format_dt(formed)}\n"
        f"{next_day_line}\n\n"
        f"⚠️ Not an entry signal. Bias only — wait for your entry model."
    )

    return AlertSignal(strategy_id, pair, direction, msg, 1.7)


def scan_monthly_slk(pair: str, df_m: pd.DataFrame, df_w: pd.DataFrame) -> Optional[AlertSignal]:
    """Monthly reject/sweep → Weekly BO."""
    return _scan_htf_slk(pair, df_m, df_w, "MONTHLY_SLK", "MN", "W", bo_max_age=3)


def scan_weekly_slk(pair: str, df_w: pd.DataFrame, df_d: pd.DataFrame) -> Optional[AlertSignal]:
    """Weekly reject/sweep → Daily BO."""
    return _scan_htf_slk(pair, df_w, df_d, "WEEKLY_SLK", "W", "D", bo_max_age=3)



def run_all_strategies(
    pair,
    frames: dict,
    enable_slk=True,
    enable_daily_crt=True,
    enable_h4_crt=True,
    enable_monthly_slk=True,
    enable_weekly_slk=True,
) -> List[AlertSignal]:
    """
    frames keys: M, W, D, H4 (DataFrames or None)
    """
    signals = []
    df_m = frames.get("M")
    df_w = frames.get("W")
    df_d = frames.get("D")
    df_4h = frames.get("H4")

    if enable_monthly_slk:
        s = scan_monthly_slk(pair, df_m, df_w)
        if s:
            signals.append(s)
    if enable_weekly_slk:
        s = scan_weekly_slk(pair, df_w, df_d)
        if s:
            signals.append(s)
    if enable_slk:
        s = scan_slk(pair, df_d, df_4h)
        if s:
            signals.append(s)
    if enable_daily_crt:
        s = scan_daily_crt(pair, df_d)
        if s:
            signals.append(s)
    if enable_h4_crt:
        s = scan_h4_crt(pair, df_4h)
        if s:
            signals.append(s)
    return signals
