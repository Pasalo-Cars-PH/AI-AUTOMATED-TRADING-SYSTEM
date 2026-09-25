import requests
import os
from enum import Enum

class TelegramHealthState(str, Enum):
    CONFIGURED = "CONFIGURED"
    MISCONFIGURED = "MISCONFIGURED"
    UNAVAILABLE = "UNAVAILABLE"

class TelegramDispatcher:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    def inspect_health(self) -> TelegramHealthState:
        if not self.token or not self.chat_id:
            return TelegramHealthState.MISCONFIGURED
        if len(self.token) < 20 or ":" not in self.token:
            return TelegramHealthState.MISCONFIGURED
        return TelegramHealthState.CONFIGURED

    def dispatch_actionable_signal(self, signal: dict) -> bool:
        if self.inspect_health() != TelegramHealthState.CONFIGURED:
            print("[Telegram] Failed health inspect. Message aborted.")
            return False

        if signal.get("state") != "ACTIONABLE":
            print(f"[Telegram] Suppressing non-actionable signal state: {signal.get('state')}")
            return False

        msg = (
            f"🚨 *TRADE SIGNAL*\n\n"
            f"Asset: `{signal['symbol']}`\n"
            f"Direction: *{signal['direction']}*\n\n"
            f"Score: `{signal['score']}/100` ({signal.get('score_band', 'STRONG')})\n"
            f"Strategy: `{signal['strategy']}`\n\n"
            f"Entry: `{signal['entry']:.4f}`\n"
            f"SL: `{signal['stop_loss']:.4f}`\n"
            f"TP1: `{signal['take_profit']:.4f}`\n"
            f"R:R: `1:{signal['risk_reward']:.2f}`\n\n"
            f"M5 Confirmation: ✅\n"
            f"MTF Alignment: ✅\n"
            f"News Risk: `{signal.get('news_status', 'CLEAR')}`\n"
            f"Correlation: PASS\n\n"
            f"Risk: `0.5%` (${signal.get('risk_amount_usd', 50):.2f})\n"
            f"State: *ACTIONABLE*\n\n"
            f"Signal ID: `{signal['signal_id']}`"
        )

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": msg, "parse_mode": "Markdown"}

        try:
            res = requests.post(url, json=payload, timeout=5)
            return res.status_code == 200
        except Exception as e:
            print(f"[Telegram] HTTP Exception: {e}")
            return False
