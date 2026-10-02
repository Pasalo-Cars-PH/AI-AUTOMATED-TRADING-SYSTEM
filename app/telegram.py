import os
import logging
import requests
from typing import Dict, Any

logger = logging.getLogger("telegram_handler")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def send_telegram_reply(chat_id: str, text: str):
    """Sends a markdown-formatted message back to the Telegram chat."""
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        logger.warning("Telegram token or chat_id missing. Skipping message send.")
        return
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")


def handle_telegram_command(data: Dict[str, Any], system_state: Dict[str, Any], daily_stats: Dict[str, Any], last_trade: Any) -> Dict[str, Any]:
    """Processes incoming Telegram commands for SMC V5.3 Engine."""
    try:
        message = data.get("message", {})
        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))
        text = message.get("text", "").strip()

        if not text or not chat_id:
            return {"status": "ignored", "reason": "empty message or chat_id"}

        # Command Parsing
        command = text.split()[0].lower()

        if command in ["/start", "/help"]:
            reply = (
                "🤖 *Institutional SMC V5.3.0 Engine Bot*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Available Commands:\n\n"
                "🔍 `/scan` or `/scan_all` - Run full market scan across canonical spot pairs\n"
                "⚡ `/enable_paper` - Enable paper trading session\n"
                "🛑 `/disable_paper` - Disable paper trading session\n"
                "🔒 `/kill` - Toggle emergency Kill Switch\n"
                "📊 `/status` - View engine status and statistics\n"
                "📜 `/journal` - View recent paper orders"
            )
            send_telegram_reply(chat_id, reply)
            return {"status": "success", "command": command}

        elif command in ["/scan", "/scan_all"]:
            send_telegram_reply(chat_id, "🔍 *Scanning canonical spot pairs with SMC V5.3.0 Engine... Please wait.*")
            
            # Import and trigger main scanner directly
            from app.main import run_smc_v1_pipeline
            result = run_smc_v1_pipeline()
            
            summary_msg = f"✅ *Scan Complete!*\nScanned pairs: {len(result.get('results', []))}\nSession Enabled: `{system_state['paper_session_enabled']}`"
            send_telegram_reply(chat_id, summary_msg)
            return {"status": "success", "command": command}

        elif command == "/enable_paper":
            system_state["paper_session_enabled"] = True
            system_state["kill_switch"] = False
            reply = (
                "✅ *PAPER SESSION ACTIVATED*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "• Mode: `PAPER_VALIDATION`\n"
                "• Session Enabled: `True`\n"
                "• Kill Switch: `False`\n"
                "• Provider: `TWELVE_DATA_SPOT`\n\n"
                "Ready to collect paper trading samples!"
            )
            send_telegram_reply(chat_id, reply)
            return {"status": "success", "command": command}

        elif command == "/disable_paper":
            system_state["paper_session_enabled"] = False
            reply = "🛑 *PAPER SESSION DISABLED*\nPaper execution has been locked."
            send_telegram_reply(chat_id, reply)
            return {"status": "success", "command": command}

        elif command == "/kill":
            current_ks = system_state.get("kill_switch", True)
            system_state["kill_switch"] = not current_ks
            status_str = "ACTIVATED (SYSTEM LOCKED)" if system_state["kill_switch"] else "DEACTIVATED (SYSTEM READY)"
            reply = f"🚨 *KILL SWITCH {status_str}*"
            send_telegram_reply(chat_id, reply)
            return {"status": "success", "command": command}

        elif command == "/status":
            reply = (
                "📊 *SYSTEM STATUS - SMC V5.3.0*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"• System Mode: `{system_state['mode']}`\n"
                f"• Paper Session: `{system_state['paper_session_enabled']}`\n"
                f"• Kill Switch: `{system_state['kill_switch']}`\n"
                f"• Data Provider: `{system_state['data_provider']}`\n"
                f"• Strict Canonical: `{system_state['strict_canonical_only']}`\n\n"
                "📈 *Daily Statistics:*\n"
                f"• Total Scans: `{daily_stats['total_scans']}`\n"
                f"• Executed Paper Orders: `{daily_stats['paper_executions']}`\n"
                f"• Rejected Candidates: `{daily_stats['rejected_candidates']}`\n"
                f"• Last Scan Time: `{daily_stats['last_scan_time']}`"
            )
            send_telegram_reply(chat_id, reply)
            return {"status": "success", "command": command}

        else:
            send_telegram_reply(chat_id, "❓ *Unknown command.* Type `/help` to view available commands.")
            return {"status": "unknown_command"}

    except Exception as e:
        logger.error(f"Error handling Telegram command: {e}")
        return {"status": "error", "message": str(e)}
