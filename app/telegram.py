import os
import logging
import requests
from typing import Dict, Any

logger = logging.getLogger("telegram_module")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_ALLOWED_CHAT_IDS = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")


def send_telegram_reply(chat_id: str, text: str) -> bool:
    """Sends a formatted Markdown reply back to the Telegram chat."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Missing TELEGRAM_BOT_TOKEN environment variable.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }

    try:
        res = requests.post(url, json=payload, timeout=5)
        return res.status_code == 200
    except Exception as e:
        logger.error(f"Error sending Telegram message: {e}")
        return False


def handle_telegram_command(data: Dict[str, Any], system_state: Dict[str, Any], daily_stats: Dict[str, Any], last_trade: Any) -> Dict[str, Any]:
    """Handles incoming Telegram commands from Webhook."""
    message = data.get("message", {})
    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))
    text = message.get("text", "").strip()

    if not chat_id:
        return {"status": "ignored", "reason": "no_chat_id"}

    # Basic authorization check
    allowed_ids = [c.strip() for c in TELEGRAM_ALLOWED_CHAT_IDS if c.strip()]
    if allowed_ids and chat_id not in allowed_ids:
        send_telegram_reply(chat_id, "⛔ *Access Denied:* Unauthorized Telegram ID.")
        return {"status": "unauthorized"}

    command = text.lower().split()[0] if text else ""

    if command in ["/start", "/help"]:
        menu_msg = (
            "🤖 *AI TRADING BOT SYSTEM MENU*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📌 *Available Commands:*\n\n"
            "• `/scan` or `/signals` - Scan all market pairs for SMC signals\n"
            "• `/status` - Check bot status & system settings\n"
            "• `/stats` - View daily scanning performance\n"
            "• `/last` - Show last generated trade signal\n"
            "• `/help` - Show this menu\n"
        )
        send_telegram_reply(chat_id, menu_msg)

    elif command in ["/scan", "/signals"]:
        send_telegram_reply(chat_id, "🔍 *Scanning market pairs with Version 4.2.0 Engine... Please wait.*")
        
        # Trigger internal scan endpoint
        try:
            from app.main import scan_all_pairs
            scan_result = scan_all_pairs()
            signals_count = scan_result.get("signals_detected", 0)

            if signals_count == 0:
                send_telegram_reply(
                    chat_id,
                    "📊 *SCAN COMPLETE*\n\n"
                    "• *Result:* `NO_VALID_SIGNAL`\n"
                    "• *Reason:* No strict M15 Pinbar or SMC Confluence (Sweep/OB) found on Spot market right now.\n\n"
                    "💡 *Tip:* Stay patient. The engine rejects low-quality setups automatically."
                )
        except Exception as e:
            logger.error(f"Scan command error: {e}")
            send_telegram_reply(chat_id, f"❌ *Scan Failed:* `{str(e)}`")

    elif command == "/status":
        status_msg = (
            "⚙️ *SYSTEM ENGINE STATUS*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"• *Version:* `4.2.0 (Spot Calibrated)`\n"
            f"• *Execution Mode:* `{system_state.get('execution_lock', 'SEMI_AUTOMATED')}`\n"
            f"• *Master Enable:* `{system_state.get('master_enable', True)}`\n"
            f"• *Kill Switch:* `{system_state.get('kill_switch', False)}`\n"
            f"• *Server Time:* `{daily_stats.get('last_scan_time', 'N/A')}`\n"
        )
        send_telegram_reply(chat_id, status_msg)

    elif command == "/stats":
        stats_msg = (
            "📈 *DAILY SCAN PERFORMANCE*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"• *Total Scans:* `{daily_stats.get('total_scans', 0)}`\n"
            f"• *Candidate Setups:* `{daily_stats.get('candidate_setups', 0)}`\n"
            f"• *Rejected Setups:* `{daily_stats.get('rejected_candidates', 0)}`\n"
            f"• *Last Scan Time:* `{daily_stats.get('last_scan_time', 'N/A')}`\n"
        )
        send_telegram_reply(chat_id, stats_msg)

    elif command == "/last":
        if last_trade:
            last_msg = (
                "📍 *LAST DETECTED TRADE SIGNAL*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"• Symbol: `{last_trade.get('symbol')}`\n"
                f"• Action: `{last_trade.get('action')}`\n"
                f"• Entry: `${last_trade.get('entry')}`\n"
                f"• Stop Loss: `${last_trade.get('sl')}`\n"
                f"• Take Profit: `${last_trade.get('tp')}`\n"
                f"• Score: `{last_trade.get('score')}/100`\n"
                f"• Timestamp: `{last_trade.get('timestamp')}`"
            )
            send_telegram_reply(chat_id, last_msg)
        else:
            send_telegram_reply(chat_id, "ℹ️ No recent signal recorded for today yet.")

    else:
        send_telegram_reply(chat_id, "❓ *Unknown command.* Type `/help` or `/start` to see available commands.")

    return {"status": "ok"}
