"""
SLK storyline strategies — Malaysian SNR + CRT confluence

Flow (Daily → 4H example):
1. Build strict A/V/OC key levels on HTF
2. Find rejection: wick into KL, body closes back
3. Optional CRT: sweep previous candle high/low, close back inside
4. LTF external body BO confirms storyline
5. Trend filter
6. A+ only: Entry / SL / TP when confluence is complete
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List

import pandas as pd

import config
from modules.structure import (
    determine_trend,
    detect_snr_breakout,
    detect_htf_range,
    detect_continuation_breaks,
    detect_crt_sweep,
    Trend,
)
from modules.key_levels import (
    get_all_key_levels,
    find_rejection_at_kl,
    closest_to_rejection,
    KeyLevelType,
)
from modules.utils import format_price, format_dt, display_symbol, minutes_until_candle_close


@dataclass
class AlertSignal:
    strategy: str
    pair: str
    direction: str
    message: str
    score: float = 1.0


def _ts(x):
    if hasattr(x, "to_pydatetime"):
        return x.to_pydatetime()
    return x


def _a_plus_levels(
    pair: str,
    direction: str,
    rej: dict,
    ext,
    kl,
    htf_range,
) -> Optional[str]:
    """
    Only for clear A+ setups.
    Entry = pullback toward BO / KL zone
    SL = beyond rejection wick
    TP1 = opposite side of HTF range mid or 1R
    TP2 = HTF range extreme
    """
    if rej is None or ext is None or kl is None:
        return None

    if direction == "BUY":
        sl = float(rej["low"])
        # entry near breakout level (discount)
        entry = float(ext.break_price)
        risk = abs(entry - sl)
        if risk <= 0:
            return None
        if htf_range is not None:
            tp1 = min(entry + risk * 1.5, htf_range.high)
            tp2 = htf_range.high
        else:
            tp1 = entry + risk * 1.5
            tp2 = entry + risk * 2.5
    else:
        sl = float(rej["high"])
        entry = float(ext.break_price)
        risk = abs(sl - entry)
        if risk <= 0:
            return None
        if htf_range is not None:
            tp1 = max(entry - risk * 1.5, htf_range.low)
            tp2 = htf_range.low
        else:
            tp1 = entry - risk * 1.5
            tp2 = entry - risk * 2.5

    # require reasonable RR to range
    if htf_range is not None:
        if direction == "BUY" and (htf_range.high - entry) < risk * 0.8:
            return None
        if direction == "SELL" and (entry - htf_range.low) < risk * 0.8:
            return None

    return (
        f"\n⭐ A+ SETUP\n"
        f"Entry zone ≈ {format_price(entry, pair)}\n"
        f"SL {format_price(sl, pair)}\n"
        f"TP1 {format_price(tp1, pair)}\n"
        f"TP2 {format_price(tp2, pair)}\n"
    )


def scan_slk(pair: str, df_daily: pd.DataFrame, df_4h: pd.DataFrame) -> Optional[AlertSignal]:
    """Daily rejection at KL → 4H external BO (+ CRT tag + trend + optional A+)."""
    if df_daily is None or df_4h is None or len(df_4h) < 30 or len(df_daily) < 12:
        return None

    levels = get_all_key_levels(df_daily, getattr(config, "OPEN_TOLERANCE", 0.0004), 80)
    if not levels:
        return None

    rej_info = find_rejection_at_kl(df_daily, levels, lookback_bars=5, max_distance_pct=0.008)
    htf_range = detect_htf_range(df_daily, lookback=50)
    crt = detect_crt_sweep(df_daily)
    daily_trend = determine_trend(df_daily, 20)

    direction = None
    path = None
    ext = None
    kl = None
    rej = None
    sweep_txt = ""

    # Path A — classic rejection + external BO
    if rej_info is not None:
        direction = rej_info["direction"]
        kl = rej_info["kl"]
        rej = rej_info
        rej_time = _ts(rej_info["time"])
        ext = detect_snr_breakout(df_4h, direction, rej_time, max_age_bars=14)
        if ext is not None:
            path = "classic"

    # Path B — CRT sweep aligned + BO (if no classic)
    if ext is None and crt is not None:
        direction = crt["direction"]
        rej_time = _ts(crt["time"])
        # find KL near the sweep
        if direction == "SELL":
            found = closest_to_rejection(levels, crt["swept"], crt["prev_low"], crt["close"], "SELL")
        else:
            found = closest_to_rejection(levels, crt["prev_high"], crt["swept"], crt["close"], "BUY")
        if found:
            kl = found[0]
        ext = detect_snr_breakout(df_4h, direction, rej_time, max_age_bars=14)
        if ext is not None:
            path = "crt"
            rej = {
                "high": float(df_daily["high"].iloc[crt["index"]]),
                "low": float(df_daily["low"].iloc[crt["index"]]),
                "close": crt["close"],
                "time": crt["time"],
                "index": crt["index"],
            }

    # Path C — HTF range bias + continuation BO (trend-aligned only)
    if ext is None and htf_range is not None and htf_range.bias in ("BUY", "SELL"):
        if daily_trend == Trend.NEUTRAL or (
            (htf_range.bias == "BUY" and daily_trend == Trend.BULLISH)
            or (htf_range.bias == "SELL" and daily_trend == Trend.BEARISH)
        ):
            direction = htf_range.bias
            cont = detect_continuation_breaks(df_4h, direction, max_age_bars=8)
            if cont:
                ext = cont[-1]
                path = "continuation"
                rej = {
                    "high": float(df_daily["high"].iloc[-1]),
                    "low": float(df_daily["low"].iloc[-1]),
                    "close": float(df_daily["close"].iloc[-1]),
                    "time": df_daily.index[-1],
                    "index": len(df_daily) - 1,
                }
                if kl is None and levels:
                    ref = ext.break_price
                    kl = min(levels, key=lambda lv: abs(lv.price - ref))

    if ext is None or direction is None or rej is None or kl is None:
        return None

    # CRT text when present and aligned
    crt_txt = ""
    if crt is not None and crt["direction"] == direction:
        side = "high" if crt["side"] == "high" else "low"
        crt_txt = (
            f"Daily CRT: swept previous candle {side} {format_price(crt['swept'], pair)}, "
            f"closed back inside.\n"
        )

    if path == "continuation":
        sweep_txt = (
            f"HTF range {format_price(htf_range.low, pair)}–{format_price(htf_range.high, pair)}; "
            f"trend-aligned continuation; "
        )
    elif path == "classic":
        # previous candle sweep description if any
        i = rej.get("index", 0)
        if i > 0:
            prev_h = float(df_daily["high"].iloc[i - 1])
            prev_l = float(df_daily["low"].iloc[i - 1])
            if direction == "SELL" and float(rej["high"]) > prev_h and float(rej["close"]) < prev_h:
                sweep_txt = f"Swept previous candle high {format_price(prev_h, pair)}, closed back below; "
            elif direction == "BUY" and float(rej["low"]) < prev_l and float(rej["close"]) > prev_l:
                sweep_txt = f"Swept previous candle low {format_price(prev_l, pair)}, closed back above; "

    fresh_tag = "fresh " if getattr(kl, "is_fresh", True) else ""
    kl_label = kl.level_type.value
    disp = display_symbol(pair)
    bt = _ts(ext.break_time)
    rt = _ts(rej["time"])
    formed = _ts(getattr(kl, "formed_at", None) or kl.timestamp)

    trend_aligned = (
        (direction == "BUY" and daily_trend == Trend.BULLISH)
        or (direction == "SELL" and daily_trend == Trend.BEARISH)
    )
    if daily_trend == Trend.NEUTRAL:
        trend_txt = "Daily trend neutral"
    elif trend_aligned:
        trend_txt = "Trend aligned with D1"
    else:
        trend_txt = "Trend counter to D1"

    next_day = False
    try:
        if bt.date() > rt.date():
            next_day = True
    except Exception:
        pass
    next_day_line = "✅ Next Day Rule" if next_day else "⬜ Same-session BO"
    emoji = "🔴" if direction == "SELL" else "🟢"

    range_line = ""
    if htf_range is not None:
        range_line = (
            f"HTF range {format_price(htf_range.low, pair)} → {format_price(htf_range.high, pair)} "
            f"(bias {htf_range.bias})\n"
        )

    path_note = {
        "classic": "External breakout confirmed",
        "crt": "CRT + external breakout confirmed",
        "continuation": "Continuation BO (trend-aligned)",
    }.get(path, "External breakout confirmed")

    # A+ only when classic/crt + trend aligned + fresh KL
    a_plus = ""
    is_a_plus = (
        path in ("classic", "crt")
        and trend_aligned
        and getattr(kl, "is_fresh", False)
        and (crt is None or crt["direction"] == direction)
    )
    if is_a_plus:
        a_plus = _a_plus_levels(pair, direction, rej, ext, kl, htf_range) or ""

    header = (
        f"{emoji} {direction} · {disp} · D1→H4\n"
        f"{path_note}\n\n"
        f"{crt_txt}"
        f"{sweep_txt}rejected {fresh_tag}{kl_label} KL @ {format_price(kl.price, pair)}.\n\n"
        f"{range_line}"
        f"External BO @ {format_price(ext.break_price, pair)} · {format_dt(bt)}\n"
        f"Rejected on {format_dt(rt)}\n"
        f"Key level {format_price(kl.price, pair)} · formed {format_dt(formed)}\n"
        f"{trend_txt}\n"
        f"{next_day_line}"
    )
    if a_plus:
        msg = header + a_plus
    else:
        msg = header + "\n\n⚠️ Not an entry signal. Bias only — wait for your entry model."

    score = 1.6 if path == "classic" else (1.55 if path == "crt" else 1.2)
    if getattr(kl, "is_fresh", False):
        score += 0.2
    if trend_aligned:
        score += 0.25
    if crt is not None and crt["direction"] == direction:
        score += 0.2
    if a_plus:
        score += 0.4

    return AlertSignal("SLK", pair, direction, msg, score)


def _htf_rejection_or_sweep(df_htf: pd.DataFrame, lookback: int = 3) -> Optional[dict]:
    if df_htf is None or len(df_htf) < 4:
        return None
    levels = get_all_key_levels(df_htf, getattr(config, "OPEN_TOLERANCE", 0.0004), 40)
    if levels:
        found = find_rejection_at_kl(df_htf, levels, lookback_bars=lookback + 1, max_distance_pct=0.01)
        if found:
            return {
                "direction": found["direction"],
                "high": found["high"],
                "low": found["low"],
                "close": found["close"],
                "time": found["time"],
                "event": "rejection",
                "kl": found["kl"],
            }
    crt = detect_crt_sweep(df_htf)
    if crt:
        return {
            "direction": crt["direction"],
            "high": crt["prev_high"] if crt["side"] == "high" else float(df_htf["high"].iloc[crt["index"]]),
            "low": crt["prev_low"] if crt["side"] == "low" else float(df_htf["low"].iloc[crt["index"]]),
            "close": crt["close"],
            "time": crt["time"],
            "event": "crt_sweep",
            "kl": None,
        }
    return None


def _scan_htf_slk(
    pair: str,
    df_htf: pd.DataFrame,
    df_ltf: pd.DataFrame,
    strategy_id: str,
    htf_label: str,
    ltf_label: str,
    bo_max_age: int = 4,
) -> Optional[AlertSignal]:
    if df_htf is None or df_ltf is None or len(df_htf) < 5 or len(df_ltf) < 20:
        return None

    htf_range = detect_htf_range(df_htf, lookback=40)
    htf_event = _htf_rejection_or_sweep(df_htf, lookback=3)
    htf_trend = determine_trend(df_htf, 15)

    direction = None
    ext = None
    path = "classic"
    kl = None
    event_txt = "rejection"

    if htf_event is not None:
        direction = htf_event["direction"]
        event_txt = htf_event["event"].replace("_", " ")
        kl = htf_event.get("kl")
        rej_time = _ts(htf_event["time"])
        ext = detect_snr_breakout(
            df_ltf, direction, rej_time, max_age_bars=max(bo_max_age * 5, 12)
        )

    if ext is None and htf_range is not None and htf_range.bias in ("BUY", "SELL"):
        aligned = htf_trend == Trend.NEUTRAL or (
            (htf_range.bias == "BUY" and htf_trend == Trend.BULLISH)
            or (htf_range.bias == "SELL" and htf_trend == Trend.BEARISH)
        )
        if aligned:
            direction = htf_range.bias
            cont = detect_continuation_breaks(df_ltf, direction, max_age_bars=max(bo_max_age * 3, 8))
            if cont:
                ext = cont[-1]
                path = "continuation"
                event_txt = "range continuation"
                htf_event = {
                    "high": float(df_htf["high"].iloc[-1]),
                    "low": float(df_htf["low"].iloc[-1]),
                    "close": float(df_htf["close"].iloc[-1]),
                    "time": df_htf.index[-1],
                    "direction": direction,
                }

    if ext is None or direction is None or htf_event is None:
        return None

    levels = get_all_key_levels(df_htf, getattr(config, "OPEN_TOLERANCE", 0.0004), 40)
    levels += get_all_key_levels(df_ltf, getattr(config, "OPEN_TOLERANCE", 0.0004), 40)
    if kl is None:
        found = closest_to_rejection(
            levels, htf_event["high"], htf_event["low"], htf_event["close"], direction
        )
        if found:
            kl = found[0]
        elif levels:
            kl = min(levels, key=lambda lv: abs(lv.price - ext.break_price))
    if kl is None:
        return None

    disp = display_symbol(pair)
    bt = _ts(ext.break_time)
    rt = _ts(htf_event["time"])
    formed = _ts(getattr(kl, "formed_at", None) or kl.timestamp)
    next_day = False
    try:
        if bt.date() > rt.date():
            next_day = True
    except Exception:
        pass
    next_day_line = "✅ Next Day Rule" if next_day else "⬜ Same-session BO"
    emoji = "🔴" if direction == "SELL" else "🟢"
    fresh_tag = "fresh " if getattr(kl, "is_fresh", True) else ""
    range_line = ""
    if htf_range is not None:
        range_line = (
            f"HTF range {format_price(htf_range.low, pair)} → {format_price(htf_range.high, pair)} "
            f"(bias {htf_range.bias})\n"
        )
    path_note = "External breakout confirmed" if path == "classic" else "Continuation BO (trend-aligned)"

    trend_aligned = (
        (direction == "BUY" and htf_trend == Trend.BULLISH)
        or (direction == "SELL" and htf_trend == Trend.BEARISH)
    )
    a_plus = ""
    if path == "classic" and trend_aligned and getattr(kl, "is_fresh", False):
        rej = {
            "high": htf_event["high"],
            "low": htf_event["low"],
            "close": htf_event["close"],
            "time": htf_event["time"],
        }
        a_plus = _a_plus_levels(pair, direction, rej, ext, kl, htf_range) or ""

    body = (
        f"{emoji} {direction} · {disp} · {htf_label}→{ltf_label}\n"
        f"{path_note}\n\n"
        f"{htf_label} {event_txt}; rejected {fresh_tag}{kl.level_type.value} KL @ {format_price(kl.price, pair)}.\n\n"
        f"{range_line}"
        f"External BO @ {format_price(ext.break_price, pair)} · {format_dt(bt)}\n"
        f"Rejected on {format_dt(rt)}\n"
        f"Key level {format_price(kl.price, pair)} · formed {format_dt(formed)}\n"
        f"{next_day_line}"
    )
    if a_plus:
        msg = body + a_plus
    else:
        msg = body + "\n\n⚠️ Not an entry signal. Bias only — wait for your entry model."

    return AlertSignal(strategy_id, pair, direction, msg, 1.7 if path == "classic" else 1.3)


def scan_monthly_slk(pair: str, df_m: pd.DataFrame, df_w: pd.DataFrame) -> Optional[AlertSignal]:
    return _scan_htf_slk(pair, df_m, df_w, "MONTHLY_SLK", "MN", "W", bo_max_age=3)


def scan_weekly_slk(pair: str, df_w: pd.DataFrame, df_d: pd.DataFrame) -> Optional[AlertSignal]:
    return _scan_htf_slk(pair, df_w, df_d, "WEEKLY_SLK", "W", "D", bo_max_age=3)


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
        # also surface simple PDH/PDL CRT near close
        crt = detect_crt_sweep(df_daily)
        if not crt:
            return None
        last = df_daily.iloc[-1]
        # alert window near daily close
        try:
            mins = minutes_until_candle_close(df_daily.index[-1], "D")
            if mins > config.CRT_ALERT_MINUTES_BEFORE_CLOSE + 30 or mins < -60:
                return None
        except Exception:
            pass
        disp = display_symbol(pair)
        emoji = "🔴" if crt["direction"] == "SELL" else "🟢"
        side = "high" if crt["side"] == "high" else "low"
        msg = (
            f"{emoji} CRT · {crt['direction']} · {disp} · D1\n"
            f"Swept previous candle {side} {format_price(crt['swept'], pair)}, closed back inside.\n"
            f"Bias only — wait for LTF confirmation / your entry model."
        )
        return AlertSignal("DAILY_CRT", pair, crt["direction"], msg, 1.1)

    direction = setup["direction"]
    disp = display_symbol(pair)
    emoji = "🔴" if direction == "SELL" else "🟢"
    msg = (
        f"{emoji} DAILY CRT · {direction} · {disp}\n"
        f"Monday range {format_price(setup['mon_low'], pair)} – {format_price(setup['mon_high'], pair)}\n"
        f"Sweep bias active. Bias only — wait for entry model."
    )
    return AlertSignal("DAILY_CRT", pair, direction, msg, 1.0)


def scan_h4_crt(pair: str, df_4h: pd.DataFrame) -> Optional[AlertSignal]:
    if df_4h is None or len(df_4h) < 5:
        return None
    crt = detect_crt_sweep(df_4h)
    if not crt:
        return None
    try:
        mins = minutes_until_candle_close(df_4h.index[-1], "H4")
        if mins > config.CRT_ALERT_MINUTES_BEFORE_CLOSE + 20 or mins < -30:
            # still allow if last closed bar was the CRT
            if crt["index"] < len(df_4h) - 2:
                return None
    except Exception:
        pass
    disp = display_symbol(pair)
    emoji = "🔴" if crt["direction"] == "SELL" else "🟢"
    side = "high" if crt["side"] == "high" else "low"
    msg = (
        f"{emoji} 4H CRT · {crt['direction']} · {disp}\n"
        f"Swept previous 4H {side} {format_price(crt['swept'], pair)}, closed back inside.\n"
        f"Bias only — wait for entry model."
    )
    return AlertSignal("H4_CRT", pair, crt["direction"], msg, 1.0)


def run_all_strategies(
    pair,
    frames: dict,
    enable_slk=True,
    enable_daily_crt=True,
    enable_h4_crt=True,
    enable_monthly_slk=True,
    enable_weekly_slk=True,
) -> List[AlertSignal]:
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
