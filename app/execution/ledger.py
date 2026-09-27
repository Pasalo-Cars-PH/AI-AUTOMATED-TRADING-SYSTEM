import json
import os
from datetime import datetime

LEDGER_FILE = "paper_ledger.json"

class PaperLedger:
    def __init__(self):
        self.trades = self._load()

    def _load(self):
        if os.path.exists(LEDGER_FILE):
            with open(LEDGER_FILE, "r") as f:
                return json.load(f)
        return []

    def _save(self):
        with open(LEDGER_FILE, "w") as f:
            json.dump(self.trades, f, indent=4)

    def record_entry(self, symbol, signal, entry_price, tp, sl):
        trade = {
            "id": len(self.trades) + 1,
            "symbol": symbol,
            "signal": signal,
            "entry_price": entry_price,
            "tp": tp,
            "sl": sl,
            "status": "OPEN",
            "timestamp": datetime.utcnow().isoformat()
        }
        self.trades.append(trade)
        self._save()
        return trade["id"]

    def update_open_trades(self, current_prices: dict):
        # Checks if current price hit TP or SL
        for trade in self.trades:
            if trade["status"] == "OPEN":
                price = current_prices.get(trade["symbol"])
                if not price: continue

                if trade["signal"] == "BUY":
                    if price >= trade["tp"]:
                        trade["status"] = "WIN"
                    elif price <= trade["sl"]:
                        trade["status"] = "LOSS"
                elif trade["signal"] == "SELL":
                    if price <= trade["tp"]:
                        trade["status"] = "WIN"
                    elif price >= trade["sl"]:
                        trade["status"] = "LOSS"
        self._save()

    def get_stats(self):
        total = len(self.trades)
        wins = sum(1 for t in self.trades if t["status"] == "WIN")
        losses = sum(1 for t in self.trades if t["status"] == "LOSS")
        open_trades = sum(1 for t in self.trades if t["status"] == "OPEN")
        win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0.0

        return {
            "total": total,
            "wins": wins,
            "losses": losses,
            "open": open_trades,
            "win_rate": round(win_rate, 1)
        }

paper_ledger = PaperLedger()
