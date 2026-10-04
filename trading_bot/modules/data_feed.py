"""OANDA v20 candles — indexed in America/New_York"""
import logging
from typing import Optional, Tuple

import requests
import pandas as pd

import config
from modules.utils import oanda_symbol

logger = logging.getLogger(__name__)


def _headers():
    return {
        "Authorization": f"Bearer {config.OANDA_API_TOKEN}",
        "Content-Type": "application/json",
        "Accept-Datetime-Format": "RFC3339",
    }


def fetch_ohlcv(symbol: str, timeframe: str = "H4", limit: int = 100) -> Optional[pd.DataFrame]:
    oanda_sym = oanda_symbol(symbol)
    url = f"{config.OANDA_API_URL}/v3/instruments/{oanda_sym}/candles"
    params = {"granularity": timeframe, "count": limit, "price": "M"}
    try:
        r = requests.get(url, headers=_headers(), params=params, timeout=15)
        r.raise_for_status()
        candles = r.json().get("candles", [])
        if not candles:
            return None
        rows = []
        for c in candles:
            mid = c.get("mid") or {}
            ts = pd.Timestamp(c["time"]).tz_convert("America/New_York")
            rows.append({
                "timestamp": ts,
                "open": float(mid.get("o", 0)),
                "high": float(mid.get("h", 0)),
                "low": float(mid.get("l", 0)),
                "close": float(mid.get("c", 0)),
                "volume": int(c.get("volume", 0)),
                "complete": bool(c.get("complete", True)),
            })
        return pd.DataFrame(rows).set_index("timestamp")
    except Exception as e:
        logger.error("OANDA %s %s: %s", symbol, timeframe, e)
        return None


def get_daily_and_4h(symbol: str):
    return (
        fetch_ohlcv(symbol, "D", getattr(config, "CANDLE_LIMIT_DAILY", 80)),
        fetch_ohlcv(symbol, "H4", getattr(config, "CANDLE_LIMIT_4H", 120)),
    )


def get_mtf_frames(symbol: str) -> dict:
    """Monthly / Weekly / Daily / 4H for multi-TF SLK."""
    return {
        "M": fetch_ohlcv(symbol, "M", 40),
        "W": fetch_ohlcv(symbol, "W", 60),
        "D": fetch_ohlcv(symbol, "D", getattr(config, "CANDLE_LIMIT_DAILY", 80)),
        "H4": fetch_ohlcv(symbol, "H4", getattr(config, "CANDLE_LIMIT_4H", 120)),
    }
