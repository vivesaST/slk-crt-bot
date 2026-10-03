"""
Multi-Strategy Trading Bot Configuration
Strategies: SLK | Daily CRT | 4H CRT
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ====================== OANDA ======================
OANDA_API_TOKEN = os.getenv(
    "OANDA_API_TOKEN",
    "988dd61a8367168c3916f2c9586bde44-5ee40fb2ef96296aa1f132140a4d2d54",
)
OANDA_ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID", "101-001-40586149-001")
OANDA_API_URL = os.getenv("OANDA_API_URL", "https://api-fxpractice.oanda.com")

# ====================== TELEGRAM ======================
TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    "8715283648:AAFdNpuXx5dsAUqubOTcJ8VvV7kAT-uksSs",
)
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "5226446668")

# ====================== PAIRS ======================
PAIRS = [
    "EUR_USD", "GBP_USD", "USD_JPY", "USD_CAD", "USD_CHF",
    "AUD_USD", "AUD_CAD", "EUR_JPY", "EUR_CAD", "EUR_AUD",
    "EUR_GBP", "EUR_NZD", "CAD_CHF", "CAD_JPY", "GBP_AUD",
    "GBP_CAD", "GBP_JPY", "GBP_CHF", "NZD_USD", "NZD_CAD",
    "XAU_USD", "XAG_USD",
]

# ====================== STRATEGIES (defaults; dashboard can override) ======================
STRATEGY_SLK = True
STRATEGY_DAILY_CRT = True
STRATEGY_H4_CRT = True

# ====================== TIMING ======================
# CRT alert: minutes before candle close
CRT_ALERT_MINUTES_BEFORE_CLOSE = 5
NY_TIMEZONE = "America/New_York"

# ====================== SLK ======================
OPEN_TOLERANCE = 0.00025
KEY_LEVEL_LOOKBACK = 50
ALERT_COOLDOWN_MINUTES = 120

# ====================== GENERAL ======================
SECRET_KEY = os.getenv("SECRET_KEY", "trading-bot-secret-change-me")
CHECK_INTERVAL_SECONDS = 30  # check often so 5-min CRT window is caught
ACTIVITY_FILE = "data/activity.json"
SETTINGS_FILE = "data/settings.json"
MAX_ACTIVITY_ENTRIES = 120
CANDLE_LIMIT_DAILY = 80
CANDLE_LIMIT_4H = 120
