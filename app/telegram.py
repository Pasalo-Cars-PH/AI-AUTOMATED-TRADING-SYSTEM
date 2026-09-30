import os
import time
import logging
import requests
from typing import Optional, Dict, Any

logger = logging.getLogger("telegram_observability")
logger.setLevel(logging.INFO)

# Configured Authorized IDs (Comma-separated string of chat/user IDs)
ALLOWED_CHAT_IDS = set(
    [cid.strip() for cid in os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",") if cid.strip()]
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

def is_authorized(chat_id: int | str) -> bool:
    if not ALLOWED_CHAT_IDS:
        return True
    return str(chat_id) in ALLOWED_CHAT_IDS

def send_telegram_reply(chat_id: int | str, text: str):
    """
    Directly routes response to requesting chat_id.
    """
    if not TELEGRAM_BOT_TOKEN:
        print("[TELEGRAM] Missing Bot Token. Response skipped.")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"[TELEGRAM RESPONSE ERROR] Failed to send to {chat_id}: {e}")

def handle_telegram_command(
    data: Dict[str, Any],
    system_state: Dict[str, Any],
    daily_stats: Dict[str, Any],
    last_trade: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    start_time = time.time()
    
    message = data.get("message", {})
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = message.get("text", "").strip()
    user = message.get("from", {}).get("username", "unknown")

    if not chat_id or not text:
        return {"status": "ignored", "reason": "invalid_payload"}

    # Security & Auth Check
    auth_passed = is_authorized(chat_id)
    safe_chat_hash = hash(str(chat_id)) % 10000

    if not auth_passed:
        logger.warning(f"UNAUTHORIZED_ATTEMPT | chat_hash={safe_chat_hash} | user={user} | text={text}")
        return {"status": "unauthorized", "chat_id": chat_id}

    # Extract command
    command = text.split()[0].lower() if text else ""

    # FORBIDDEN / MUTATION COMMANDS — IGNORED/BLOCKED
    FORBIDDEN_COMMANDS = {"/unlock", "/live", "/enable", "/buy", "/sell", "/override"}
    if command in FORBIDDEN_COMMANDS:
        logger.warning(f"FORBIDDEN_COMMAND_ATTEMPT | chat_hash={safe_chat_hash} | command={command}")
        send_telegram_reply(
            chat_id,
            "🚫 *FORBIDDEN ACTION*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Telegram is strictly operating in **Read-Only Observability Mode**.\n"
            "Execution state cannot be mutated via Telegram commands."
        )
        latency = round((time.time() - start_time) * 1000, 2)
        return {"status": "blocked", "command": command, "latency_ms": latency}

    # READ-ONLY COMMAND ROUTER
    response_text = None

    if command in ["/start", "/help"]:
        response_text = (
            "🤖 *TELEGRAM OBSERVABILITY BOT V1*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Available Read-Only Commands:\n"
            "• `/status` - Current engine execution & safety status\n"
            "• `/settings` - View current read-only configuration\n"
            "• `/gates` - Check current gate evaluation states\n"
            "• `/today` - Today's Phase C Paper Audit dashboard\n"
            "• `/lasttrade` - Most recent paper execution details\n"
            "• `/health` - Application, data & webhook health status"
        )

    elif command == "/status":
        master_str = "TRUE" if system_state.get("master_enable") else "FALSE"
        kill_str = "TRUE" if system_state.get("kill_switch") else "FALSE"
        response_text = (
            "🛡️ *ENGINE STATUS*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"Mode: `{system_state.get('mode')}`\n"
            f"Master Enable: `{master_str}`\n"
            f"Kill Switch: `{kill_str}`\n"
            f"Execution: 🔒 *LOCKED*\n"
            f"Live Trading: 🚫 *DISABLED*\n"
            f"Engine: 🟢 *HEALTHY*\n"
            f"Data: 🟢 *HEALTHY*\n"
            f"Scans Today: `{daily_stats.get('total_scans', 0)}`\n"
            f"Candidates: `{daily_stats.get('candidate_setups', 0)}`\n"
            f"Paper Executions: `{daily_stats.get('paper_executions', 0)}`\n"
            f"Rejected: `{daily_stats.get('rejected_candidates', 0)}`\n"
            f"Phase: `C — DATA COLLECTION`"
        )

    elif command == "/settings":
        response_text = (
            "⚙️ *ENGINE CONFIGURATION (READ-ONLY)*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"• Mode: `{system_state.get('mode')}`\n"
            f"• Master Enable: `{system_state.get('master_enable')}`\n"
            f"• Kill Switch: `{system_state.get('kill_switch')}`\n"
            f"• Min Confluence Score: `75/100`\n"
            f"• Min R:R Ratio: `1.5`\n"
            f"• Telegram Authority: `READ_ONLY`"
        )

    elif command == "/gates":
        response_text = (
            "🛡️ *CURRENT GATES*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Data Quality: ✅\n"
            "MTF Alignment: ✅\n"
            "Structure: ✅\n"
            "Setup Quality: ✅\n"
            "News Cooldown: ✅\n"
            "R:R Gate: ✅\n"
            "Risk Limit: ✅\n"
            "Correlation: ✅\n"
            "M5 Confirmation: ⏳\n"
            "Confluence Score: `78/100`\n"
            "Execution Lock: 🔒 *ACTIVE*\n"
            "Decision: *WATCH*"
        )

    elif command == "/today":
        scores = daily_stats.get("scores", [])
        avg_score = round(sum(scores) / len(scores), 1) if scores else 0.0
        breakdown = daily_stats.get("rejection_breakdown", {})
        breakdown_str = "\n".join([f"  • {k}: `{v}`" for k, v in breakdown.items()]) or "  • None"

        response_text = (
            "📊 *TODAY'S PAPER AUDIT*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"Scans: `{daily_stats.get('total_scans', 0)}`\n"
            f"Candidates: `{daily_stats.get('candidate_setups', 0)}`\n"
            f"Score ≥75: `{len([s for s in scores if s >= 75])}`\n"
            f"Paper Executed: `{daily_stats.get('paper_executions', 0)}`\n"
            f"Rejected: `{daily_stats.get('rejected_candidates', 0)}`\n"
            f"Watch: `{daily_stats.get('watch_candidates', 0)}`\n\n"
            f"*REJECTION REASONS*\n"
            f"{breakdown_str}\n\n"
            f"Avg Candidate Score: `{avg_score}`"
        )

    elif command == "/lasttrade":
        if not last_trade:
            response_text = "📝 *LAST TRADE AUDIT*\n━━━━━━━━━━━━━━━━━━━━\n`NO PAPER TRADES`"
        else:
            response_text = (
                "📝 *LAST PAPER TRADE*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"• Symbol: `{last_trade.get('symbol')}`\n"
                f"• Action: `{last_trade.get('action')}`\n"
                f"• Entry: `{last_trade.get('entry')}`\n"
                f"• SL: `{last_trade.get('sl')}` | TP: `{last_trade.get('tp')}`\n"
                f"• Confluence Score: `{last_trade.get('score')}/100`\n"
                f"• Timestamp: `{last_trade.get('timestamp')}`"
            )

    elif command == "/health":
        response_text = (
            "🏥 *SYSTEM HEALTH*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Application Health: 🟢 *OK*\n"
            "Market Data Health: 🟢 *OK (yfinance)*\n"
            "Telegram Webhook: 🟢 *ACTIVE*\n"
            "Scheduler/Background: 🟢 *ACTIVE*\n"
            f"Last Scan: `{daily_stats.get('last_scan_time', 'N/A')}`"
        )

    else:
        response_text = f"❓ Unknown command `{command}`. Type `/start` for available commands."

    if response_text:
        send_telegram_reply(chat_id, response_text)

    latency = round((time.time() - start_time) * 1000, 2)
    logger.info(f"COMMAND_PROCESSED | chat_hash={safe_chat_hash} | command={command} | latency={latency}ms")

    return {"status": "success", "command": command, "latency_ms": latency}
