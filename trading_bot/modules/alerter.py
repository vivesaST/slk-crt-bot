"""Telegram alerts"""
import logging
import asyncio
import requests
import config

logger = logging.getLogger(__name__)


class TelegramAlerter:
    def __init__(self):
        self.token = config.TELEGRAM_BOT_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID

    def send(self, text: str) -> bool:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            r = requests.post(
                url,
                json={"chat_id": self.chat_id, "text": text},
                timeout=15,
            )
            r.raise_for_status()
            return True
        except Exception as e:
            logger.error("Telegram failed: %s", e)
            print(text)
            return False

    def send_sync(self, text: str) -> bool:
        return self.send(text)


def test_alert_slk() -> bool:
    msg = (
        "🧪 TEST · SLK\n\n"
        "This is a test for SLK (Structure · Liquidity · Key Levels).\n"
        "If you see this, SLK alerts are working."
    )
    return TelegramAlerter().send(msg)


def test_alert_daily_crt() -> bool:
    msg = (
        "🧪 TEST · DAILY CRT\n\n"
        "This is a test for Daily CRT (5 min before daily close).\n"
        "If you see this, Daily CRT alerts are working."
    )
    return TelegramAlerter().send(msg)


def test_alert_h4_crt() -> bool:
    msg = (
        "🧪 TEST · 4H CRT\n\n"
        "This is a test for 4H CRT (5 min before C2 close).\n"
        "If you see this, 4H CRT alerts are working."
    )
    return TelegramAlerter().send(msg)


def test_alert_monthly_slk() -> bool:
    msg = (
        "🧪 TEST · MONTHLY SLK\n\n"
        "Monthly reject/sweep → Weekly BO.\n"
        "If you see this, Monthly SLK alerts are working."
    )
    return TelegramAlerter().send(msg)


def test_alert_weekly_slk() -> bool:
    msg = (
        "🧪 TEST · WEEKLY SLK\n\n"
        "Weekly reject/sweep → Daily BO.\n"
        "If you see this, Weekly SLK alerts are working."
    )
    return TelegramAlerter().send(msg)
