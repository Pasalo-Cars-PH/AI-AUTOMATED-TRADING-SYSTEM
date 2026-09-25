import os
import requests
from typing import Dict, Any, List
from app.paper.account import paper_account

class PaperAnalytics:
    @staticmethod
    def get_performance_summary() -> Dict[str, Any]:
        closed = paper_account.closed_positions
        total_trades = len(closed)
        
        if total_trades == 0:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "net_pnl": 0.0,
                "average_r": 0.0,
                "max_drawdown": 0.0
            }

        wins = [p for p in closed if p.realized_pnl > 0]
        losses = [p for p in closed if p.realized_pnl < 0]
        gross_profit = sum(p.realized_pnl for p in wins)
        gross_loss = abs(sum(p.realized_pnl for p in losses))
        
        win_rate = round(len(wins) / total_trades * 100, 2)
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else gross_profit
        net_pnl = round(sum(p.realized_pnl for p in closed), 2)
        avg_r = round(sum(p.r_multiple for p in closed) / total_trades, 2)

        return {
            "total_trades": total_trades,
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "net_pnl": net_pnl,
            "average_r": avg_r,
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2)
        }

class PaperTelegramDispatcher:
    @staticmethod
    def notify_trade_open(pos: Any):
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not token or not chat_id: return

        msg = (
            f"🟡 *PAPER TRADE OPENED*\n\n"
            f"Symbol: *{pos.symbol}*\n"
            f"Direction: *{pos.direction}*\n"
            f"Score: `{pos.score}/100`\n\n"
            f"Entry: `{pos.simulated_entry:.4f}`\n"
            f"SL: `{pos.stop_loss:.4f}`\n"
            f"TP: `{pos.take_profit:.4f}`\n\n"
            f"Risk: `{pos.risk_percentage}%`\n"
            f"Strategy: `{pos.strategy}`\n"
            f"M5 Confirmation: ✅\n"
            f"Execution: *PAPER ONLY*\n"
            f"Real Broker Order: ❌ NONE\n"
            f"Trade ID: `{pos.position_id}`"
        )
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
                timeout=3
            )
        except Exception: pass

    @staticmethod
    def notify_trade_close(pos: Any):
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not token or not chat_id: return

        icon = "🟢" if pos.realized_pnl >= 0 else "🔴"
        msg = (
            f"{icon} *PAPER TRADE CLOSED*\n\n"
            f"Symbol: *{pos.symbol}*\n"
            f"Direction: *{pos.direction}*\n\n"
            f"Entry: `{pos.simulated_entry:.4f}`\n"
            f"Exit: `{pos.exit_price:.4f}`\n\n"
            f"P&L: *${pos.realized_pnl:+.2f}*\n"
            f"R Multiple: *{pos.r_multiple:+.2f}R*\n"
            f"Exit Reason: `{pos.exit_reason}`"
        )
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
                timeout=3
            )
        except Exception: pass
