import os
import httpx
import logging

logger = logging.getLogger("trading_bot")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

async def execute_vantage_trade(symbol: str, action: str, lot_size: float, sl: float, tp: float):
    """
    Sends direct actionable signal alerts to Telegram for 1-tap manual execution on MT4/MT5 Mobile.
    100% Free - Zero Cloud Cost!
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("TELEGRAM credentials missing. Cannot send execution signal.")
        return False

    clean_symbol = symbol.replace("=X", "").replace("USDT", "USD")
    emoji = "🟢 BUY SIGNAL" if action.upper() == "BUY" else "🔴 SELL SIGNAL"

    message = (
        f"{emoji}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📊 **Asset:** `{clean_symbol}`\n"
        f"⚡ **Action:** **{action.upper()}**\n"
        f"📏 **Lot Size:** `{lot_size}`\n"
        f"🛑 **Stop Loss (SL):** `{sl}`\n"
        f"🎯 **Take Profit (TP):** `{tp}`\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💡 *I-type/i-set agad sa Vantage MT4/MT5 App sa Tablet!*"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=5.0)
            if resp.status_code == 200:
                logger.info(f"TELEGRAM_SIGNAL_SENT | {action} {clean_symbol}")
                return True
            else:
                logger.error(f"TELEGRAM_SIGNAL_FAILED | Status: {resp.status_code} | {resp.text}")
                return False
    except Exception as e:
        logger.error(f"TELEGRAM_SIGNAL_ERROR | Error: {e}")
        return False
