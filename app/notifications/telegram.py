import requests
import os

class TelegramDispatcher:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    def inspect_health(self) -> str:
        if self.token and self.chat_id:
            return "configured"
        return "misconfigured"

    def dispatch_actionable_signal(self, signal: dict) -> bool:
        if self.inspect_health() != "configured":
            return False

        msg = (
            f"🚀 *ORDER SUBMITTED*\n\n"
            f"Signal ID: `{signal.get('signal_id', 'N/A')}`\n"
            f"Symbol: `{signal.get('symbol')}`\n"
            f"Direction: *{signal.get('direction')}*\n"
            f"Entry: `{signal.get('entry'):.4f}`\n"
            f"SL: `{signal.get('stop_loss'):.4f}`\n"
            f"TP: `{signal.get('take_profit'):.4f}`\n"
            f"Score: `{signal.get('score')}/100`\n"
            f"State: *ACTIONABLE*"
        )

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            res = requests.post(url, json={"chat_id": self.chat_id, "text": msg, "parse_mode": "Markdown"}, timeout=5)
            return res.status_code == 200
        except Exception:
            return False
