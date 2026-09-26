import os
import httpx
import logging
from app.market.service import market_service
from app.strategy.evaluator import strategy_evaluator
from app.paper.account import paper_account

logger = logging.getLogger("trading_bot")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

async def send_telegram_message(message: str, chat_id: str = None):
    target_chat = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target_chat:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": message,
        "parse_mode": "HTML"
    }

    try:
        async with httpx.AsyncClient() as client:
            await client.post(url, json=payload, timeout=10.0)
    except Exception as e:
        logger.error(f"Error sending Telegram message: {e}")

async def handle_telegram_command(data: dict):
    """Handles incoming commands like /start, /signals, /status"""
    message = data.get("message", {})
    text = message.get("text", "").strip()
    chat_id = str(message.get("chat", {}).get("id", ""))

    if not text or not chat_id:
        return

    if text == "/start":
        msg = (
            "🤖 <b>AI Automated Trading System is LIVE on Render!</b>\n\n"
            "Monitoring strategy on M5/M15 timeframe...\n"
            "Use /signals for market analysis or /status for account stats."
        )
        await send_telegram_message(msg, chat_id)

    elif text == "/signals":
        symbols = ["BTCUSD", "ETHUSD", "SOLUSD"]
        response = "🤖 <b>Multi-Asset Strategy Engine Analysis</b>\n\n"
        for sym in symbols:
            candles = market_service.get_candles(sym, timeframe="M5")
            if candles:
                analysis = strategy_evaluator.evaluate_m5_setup(sym, candles)
                response += f"• <b>{sym}:</b> {analysis['action']} (Score: {analysis['score']}/100) @ ${analysis['latest_price']:,.2f}\n"
            else:
                response += f"• <b>{sym}:</b> Fetching data...\n"
        
        await send_telegram_message(response, chat_id)

    elif text == "/status":
        status_msg = (
            f"📊 <b>Paper Account Status</b>\n\n"
            f"<b>Balance:</b> ${paper_account.balance:,.2f}\n"
            f"<b>Equity:</b> ${paper_account.equity:,.2f}\n"
            f"<b>Open Positions:</b> {len(paper_account.open_positions)}\n"
            f"<b>Consecutive Losses:</b> {paper_account.consecutive_losses}"
        )
        await send_telegram_message(status_msg, chat_id)
