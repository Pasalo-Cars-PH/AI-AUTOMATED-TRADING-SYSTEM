import os
import logging
import requests
import threading
from typing import Dict, Any

logger = logging.getLogger("smc_engine_v5_3")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_ALLOWED_CHAT_IDS = {
    x.strip() for x in os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",") if x.strip()
}
FORBIDDEN_TRADING_COMMANDS = {"/unlock", "/buy", "/sell", "/order", "/trade", "/execute"}

def is_authorized(chat_id: str) -> bool:
    """Fail-closed when an explicit Telegram allowlist is configured."""
    if not TELEGRAM_ALLOWED_CHAT_IDS:
        return True
    return str(chat_id) in TELEGRAM_ALLOWED_CHAT_IDS

def send_telegram_reply(chat_id: str, text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        logger.warning("Telegram Bot Token or Chat ID missing.")
        return False
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    
    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.status_code == 200
    except Exception as e:
        logger.error(f"Failed to send Telegram reply: {e}")
        return False


def run_async_scan(chat_id: str, system_state: Dict[str, Any]):
    """Executes the scan in a background thread to prevent Telegram Webhook timeout."""
    try:
        backend_url = os.getenv("RENDER_EXTERNAL_URL", "http://127.0.0.1:10000").rstrip("/")
        res = requests.get(f"{backend_url}/scan-all", timeout=120)
        scan_data = res.json()
        
        accepted = scan_data.get("accepted_signals", 0)
        if accepted == 0:
            reply = (
                "✅ *Scan Complete!*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "• Scanned Pairs: `3` (XAUUSD, GBPUSD, EURUSD)\n"
                f"• Session Enabled: `{system_state['paper_session_enabled']}`\n"
                "• Valid SMC Signals Found: `0`\n\n"
                "ℹ️ No A+ SMC setups detected right now."
            )
            send_telegram_reply(chat_id, reply)
    except Exception as scan_err:
        logger.error(f"Async scan failed: {scan_err}")
        send_telegram_reply(chat_id, f"❌ Scan Execution Failed: `{scan_err}`")


def handle_telegram_command(data: Dict[str, Any], system_state: Dict[str, Any], daily_stats: Dict[str, Any], last_trade: Any = None) -> Dict[str, Any]:
    try:
        message = data.get("message") or data.get("edited_message")
        if not message:
            return {"status": "ignored", "reason": "no_message"}
            
        chat_id = str(message.get("chat", {}).get("id"))
        text = str(message.get("text", "")).strip()
        
        if not text.startswith("/"):
            return {"status": "ignored", "reason": "not_a_command"}
            
        command = text.split()[0].lower()
        
        if not is_authorized(chat_id):
            send_telegram_reply(chat_id, "🚫 Unauthorized Telegram chat.")
            return {"status": "blocked", "reason": "unauthorized"}

        if command in FORBIDDEN_TRADING_COMMANDS:
            send_telegram_reply(chat_id, "🔒 Trading execution commands are disabled. Paper-only safety lock remains active.")
            return {"status": "blocked", "reason": "forbidden_command"}

        # /start or /help
        if command in ["/start", "/help"]:
            reply = (
                "🤖 *INSTITUTIONAL SMC V5.3 SPOT ENGINE*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Available Commands:\n"
                "• `/start_session` - Enable Paper Session\n"
                "• `/stop_session` - Disable Paper Session & Enable Kill Switch\n"
                "• `/status` - Check Engine Health & Operational State\n"
                "• `/scan` - Execute Manual Multi-Timeframe SMC Scan\n"
                "• `/last_trade` - View Most Recent Executed Paper Trade\n"
                "• `/stats` - View Daily Execution Statistics"
            )
            send_telegram_reply(chat_id, reply)
            return {"status": "success", "command": command}

        # /start_session
        elif command in ["/start_session", "/enable_paper"]:
            system_state["paper_session_enabled"] = True
            system_state["kill_switch"] = False
            reply = (
                "✅ *PAPER SESSION ACTIVATED*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"• Mode: `{system_state['mode']}`\n"
                f"• Session Enabled: `{system_state['paper_session_enabled']}`\n"
                f"• Kill Switch: `{system_state.get('kill_switch', True)}`\n"
                f"• Provider: `{system_state['data_provider']}`\n\n"
                "Ready to collect paper trading samples!"
            )
            send_telegram_reply(chat_id, reply)
            return {"status": "success", "command": command}

        # /stop_session
        elif command in ["/stop_session", "/disable_paper"]:
            system_state["paper_session_enabled"] = False
            system_state["kill_switch"] = True
            reply = (
                "🛑 *PAPER SESSION TERMINATED*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "• Paper Trading Session: `DISABLED`\n"
                "• Safety Kill Switch: `ACTIVE`\n\n"
                "Engine is locked in Fail-Closed mode."
            )
            send_telegram_reply(chat_id, reply)
            return {"status": "success", "command": command}

        # /status
        elif command == "/status":
            reply = (
                "📊 *ENGINE OPERATIONAL STATUS*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"• System Mode: `{system_state.get('mode', 'PAPER')}`\n"
                f"• Paper Session: `{system_state.get('paper_session_enabled', False)}`\n"
                f"• Kill Switch: `{system_state['kill_switch']}`\n"
                f"• Data Provider: `{system_state.get('data_provider', 'TwelveData')}`\n"
                f"• Scans Today: `{daily_stats.get('total_scans', 0)}`\n"
                f"• Last Scan: `{daily_stats.get('last_scan_time', 'N/A')}`"
            )
            send_telegram_reply(chat_id, reply)
            return {"status": "success", "command": command}

        # /scan (ASYNC NON-BLOCKING EXECUTION)
        elif command == "/scan":
            send_telegram_reply(chat_id, "🔍 *Scanning canonical spot pairs (XAUUSD, GBPUSD, EURUSD)... Please wait.*")
            
            # Start scan in a background thread to return instant 200 OK to Telegram Webhook
            thread = threading.Thread(target=run_async_scan, args=(chat_id, system_state))
            thread.start()
            
            return {"status": "success", "command": command}

        # /last_trade
        elif command in ["/last_trade", "/lasttrade"]:
            if not last_trade:
                reply = "ℹ️ No paper trades executed yet in this active session."
            else:
                reply = (
                    "📝 *LAST EXECUTED PAPER ORDER*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"• Trade ID: `{last_trade['paper_trade_id']}`\n"
                    f"• Symbol: `{last_trade['symbol']}`\n"
                    f"• Direction: `{last_trade['direction']}`\n"
                    f"• Entry Price: `${last_trade['entry_price']}`\n"
                    f"• SL: `${last_trade['sl']}` | TP: `${last_trade['tp']}`\n"
                    f"• Score: `{last_trade['score']}/100`"
                )
            send_telegram_reply(chat_id, reply)
            return {"status": "success", "command": command}

        # /stats
        elif command == "/stats":
            reply = (
                "📈 *DAILY PERFORMANCE METRICS*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"• Total Market Scans: `{daily_stats['total_scans']}`\n"
                f"• Setups Analyzed: `{daily_stats['candidate_setups']}`\n"
                f"• Paper Executions: `{daily_stats['paper_executions']}`\n"
                f"• Rejected Candidates: `{daily_stats['rejected_candidates']}`\n"
                f"• Last Scan Time: `{daily_stats['last_scan_time']}`"
            )
            send_telegram_reply(chat_id, reply)
            return {"status": "success", "command": command}

        else:
            send_telegram_reply(chat_id, "❓ Unknown command. Type `/help` for available options.")
            return {"status": "ignored", "reason": "unknown_command"}

    except Exception as e:
        logger.error(f"Error handling Telegram command: {e}")
        return {"status": "error", "message": str(e)}
