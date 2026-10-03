"""Background scanner — respects strategy toggles from dashboard"""
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List

import config
from modules.data_feed import get_daily_and_4h
from modules.strategies import run_all_strategies
from modules.alerter import TelegramAlerter
from modules.utils import now_ny

logger = logging.getLogger("BotRunner")


class BotRunner:
    def __init__(self):
        self._thread = None
        self._stop = threading.Event()
        self.is_running = False
        self.last_scan = None
        self.alerter = TelegramAlerter()
        self.last_alert: Dict[str, datetime] = {}  # key: strategy|pair
        self._ensure_files()
        self.settings = self._load_settings()

    def _ensure_files(self):
        os.makedirs("data", exist_ok=True)
        if not os.path.exists(config.ACTIVITY_FILE):
            with open(config.ACTIVITY_FILE, "w") as f:
                json.dump([], f)
        if not os.path.exists(config.SETTINGS_FILE):
            self._save_settings({
                "slk": True,
                "daily_crt": True,
                "h4_crt": True,
            })

    def _load_settings(self) -> dict:
        try:
            with open(config.SETTINGS_FILE) as f:
                return json.load(f)
        except Exception:
            return {"slk": True, "daily_crt": True, "h4_crt": True}

    def _save_settings(self, s: dict):
        with open(config.SETTINGS_FILE, "w") as f:
            json.dump(s, f, indent=2)
        self.settings = s

    def update_settings(self, slk: bool = None, daily_crt: bool = None, h4_crt: bool = None):
        s = self._load_settings()
        if slk is not None:
            s["slk"] = bool(slk)
        if daily_crt is not None:
            s["daily_crt"] = bool(daily_crt)
        if h4_crt is not None:
            s["h4_crt"] = bool(h4_crt)
        self._save_settings(s)

    def _log(self, message: str, level: str = "info", pair: str = None, strategy: str = None):
        try:
            with open(config.ACTIVITY_FILE) as f:
                acts = json.load(f)
        except Exception:
            acts = []
        acts.insert(0, {
            "time": now_ny().strftime("%Y-%m-%d %H:%M:%S"),
            "level": level,
            "message": message,
            "pair": pair,
            "strategy": strategy,
        })
        acts = acts[: config.MAX_ACTIVITY_ENTRIES]
        with open(config.ACTIVITY_FILE, "w") as f:
            json.dump(acts, f, indent=2)

    def get_activities(self, limit=50) -> List[dict]:
        try:
            with open(config.ACTIVITY_FILE) as f:
                return json.load(f)[:limit]
        except Exception:
            return []

    def _can_alert(self, key: str) -> bool:
        last = self.last_alert.get(key)
        if last is None:
            return True
        return (now_ny() - last) > timedelta(minutes=config.ALERT_COOLDOWN_MINUTES)

    def _process_pair(self, pair: str):
        s = self.settings
        self._log(f"Scanning {pair}", "scan", pair)
        df_d, df_4 = get_daily_and_4h(pair)
        if df_d is None and df_4 is None:
            self._log(f"No data for {pair}", "warning", pair)
            return

        signals = run_all_strategies(
            pair, df_d, df_4,
            enable_slk=s.get("slk", True),
            enable_daily_crt=s.get("daily_crt", True),
            enable_h4_crt=s.get("h4_crt", True),
        )
        for sig in signals:
            key = f"{sig.strategy}|{pair}"
            if not self._can_alert(key):
                self._log(f"Cooldown {sig.strategy} {pair}", "info", pair, sig.strategy)
                continue
            self._log(f"{sig.strategy} {sig.direction} {pair}", "alert", pair, sig.strategy)
            ok = self.alerter.send(sig.message)
            self._log(
                f"Telegram {'sent' if ok else 'failed'} {sig.strategy}",
                "success" if ok else "error",
                pair,
                sig.strategy,
            )
            self.last_alert[key] = now_ny()

    def _loop(self):
        self._log("Bot started", "success")
        while not self._stop.is_set():
            self.last_scan = now_ny().strftime("%Y-%m-%d %H:%M:%S NY")
            self._log(f"Full scan @ {self.last_scan}", "scan")
            for pair in config.PAIRS:
                if self._stop.is_set():
                    break
                try:
                    self._process_pair(pair)
                except Exception as e:
                    self._log(f"Error {pair}: {e}", "error", pair)
                    logger.exception(pair)
                time.sleep(0.8)
            for _ in range(config.CHECK_INTERVAL_SECONDS):
                if self._stop.is_set():
                    break
                time.sleep(1)
        self.is_running = False
        self._log("Bot stopped", "warning")

    def start(self) -> bool:
        if self.is_running:
            return False
        self._stop.clear()
        self.is_running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> bool:
        if not self.is_running:
            return False
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
        self.is_running = False
        return True

    def status(self) -> dict:
        return {
            "running": self.is_running,
            "last_scan": self.last_scan,
            "pairs": config.PAIRS,
            "settings": self.settings,
            "interval": config.CHECK_INTERVAL_SECONDS,
        }


runner = BotRunner()
