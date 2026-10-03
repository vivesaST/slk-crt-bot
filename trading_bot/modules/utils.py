"""Shared utilities — New York timezone"""
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UTC = timezone.utc


def now_ny() -> datetime:
    return datetime.now(NY)


def format_price(price: float, pair: str) -> str:
    clean = pair.replace("/", "_").replace("-", "_").upper()
    if "JPY" in clean:
        return f"{price:.3f}"
    if "XAU" in clean or "XAG" in clean:
        return f"{price:.2f}"
    return f"{price:.5f}"


def format_dt(dt: datetime) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(NY).strftime("%a %d %b, %H:%M")


def oanda_symbol(pair: str) -> str:
    p = pair.replace("/", "_").replace("-", "_").upper()
    if "_" not in p and len(p) == 6:
        p = p[:3] + "_" + p[3:]
    mapping = {
        "XAUUSD": "XAU_USD",
        "XAGUSD": "XAG_USD",
        "US30": "US30_USD",
        "USOIL": "WTICO_USD",
    }
    return mapping.get(p.replace("_", ""), p)


def display_symbol(pair: str) -> str:
    return pair.replace("_", "").replace("/", "")


def minutes_until_candle_close(candle_start: datetime, granularity: str) -> float:
    """
    Return minutes remaining until this candle closes.
    granularity: 'H4' or 'D'
    candle_start must be timezone-aware (NY preferred).
    """
    if candle_start.tzinfo is None:
        candle_start = candle_start.replace(tzinfo=NY)
    else:
        candle_start = candle_start.astimezone(NY)

    if granularity == "H4":
        duration = timedelta(hours=4)
    elif granularity == "D":
        # OANDA daily candles typically 17:00 NY previous day → 17:00 NY
        duration = timedelta(hours=24)
    else:
        duration = timedelta(hours=1)

    close_time = candle_start + duration
    remaining = (close_time - now_ny()).total_seconds() / 60.0
    return remaining
