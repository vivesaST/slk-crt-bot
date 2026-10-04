"""Background scanner — strategy toggles + dynamic pairs"""
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List

import config
from modules.data_feed import get_mtf_frames
from modules.strategies import run_all_strategies
from modules.alerter import TelegramAlerter
from modules.utils import now_ny, oanda_symbol

logger = logging.getLogger("BotRunner")


class BotRunner:
    def __init__(self):
        self._thread = None
        self._stop = threading.Event()
        self.is_running = False
        self.last_scan = None
        self.alerter = TelegramAlerter()
        self.last_alert: Dict[str, datetime] = {}
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
                "monthly_slk": True,
                "weekly_slk": True,
                "pairs": list(config.PAIRS),
            })

    def _load_settings(self) -> dict:
        try:
            with open(config.SETTINGS_FILE) as f:
                s = json.load(f)
            if "pairs" not in s or not s["pairs"]:
                s["pairs"] = list(config.PAIRS)
            return s
        except Exception:
            return {"slk": True, "daily_crt": True, "h4_crt": True, "monthly_slk": True, "weekly_slk": True, "pairs": list(config.PAIRS)}

    def _save_settings(self, s: dict):
        with open(config.SETTINGS_FILE, "w") as f:
            json.dump(s, f, indent=2)
        self.settings = s

    def get_pairs(self) -> List[str]:
        return list(self.settings.get("pairs") or config.PAIRS)

    def update_settings(self, slk=None, daily_crt=None, h4_crt=None, monthly_slk=None, weekly_slk=None):
        s = self._load_settings()
        if slk is not None:
            s["slk"] = bool(slk)
        if daily_crt is not None:
            s["daily_crt"] = bool(daily_crt)
        if h4_crt is not None:
            s["h4_crt"] = bool(h4_crt)
        if monthly_slk is not None:
            s["monthly_slk"] = bool(monthly_slk)
        if weekly_slk is not None:
            s["weekly_slk"] = bool(weekly_slk)
        self._save_settings(s)

    def add_pair(self, pair: str) -> dict:
        pair = oanda_symbol(pair.strip())
        s = self._load_settings()
        pairs = list(s.get("pairs") or [])
        if pair in pairs:
            return {"success": False, "message": f"{pair} already in list", "pairs": pairs}
        pairs.append(pair)
        s["pairs"] = pairs
        self._save_settings(s)
        return {"success": True, "message": f"Added {pair}", "pairs": pairs}

    def remove_pair(self, pair: str) -> dict:
        pair = oanda_symbol(pair.strip())
        s = self._load_settings()
        pairs = list(s.get("pairs") or [])
        if pair not in pairs:
            return {"success": False, "message": f"{pair} not in list", "pairs": pairs}
        pairs = [p for p in pairs if p != pair]
        s["pairs"] = pairs
        self._save_settings(s)
        return {"success": True, "message": f"Removed {pair}", "pairs": pairs}

    def _log(self, message, level="info", pair=None, strategy=None):
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

    def get_activities(self, limit=50):
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
        frames = get_mtf_frames(pair)
        if all(v is None for v in frames.values()):
            self._log(f"No data for {pair}", "warning", pair)
            return

        signals = run_all_strategies(
            pair, frames,
            enable_slk=s.get("slk", True),
            enable_daily_crt=s.get("daily_crt", True),
            enable_h4_crt=s.get("h4_crt", True),
            enable_monthly_slk=s.get("monthly_slk", True),
            enable_weekly_slk=s.get("weekly_slk", True),
        )
        if not signals:
            self._log(f"No setup for {pair}", "info", pair)
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
        self._log("Bot started (scan every 4 hours)", "success")
        while not self._stop.is_set():
            self.last_scan = now_ny().strftime("%Y-%m-%d %H:%M:%S NY")
            pairs = self.get_pairs()
            self._log(f"Full scan @ {self.last_scan} · {len(pairs)} pairs", "scan")
            for pair in pairs:
                if self._stop.is_set():
                    break
                try:
                    self._process_pair(pair)
                except Exception as e:
                    self._log(f"Error {pair}: {e}", "error", pair)
                    logger.exception(pair)
                time.sleep(0.8)
            # Wait 4 hours (or until stop)
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
            "pairs": self.get_pairs(),
            "settings": {
                "slk": self.settings.get("slk", True),
                "daily_crt": self.settings.get("daily_crt", True),
                "h4_crt": self.settings.get("h4_crt", True),
                "monthly_slk": self.settings.get("monthly_slk", True),
                "weekly_slk": self.settings.get("weekly_slk", True),
            },
            "interval": config.CHECK_INTERVAL_SECONDS,
            "interval_label": f"{config.CHECK_INTERVAL_SECONDS // 3600}h",
        }


runner = BotRunner()
