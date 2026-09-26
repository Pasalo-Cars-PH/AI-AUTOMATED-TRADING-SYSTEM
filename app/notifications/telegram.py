import os
import httpx
import logging

logger = logging.getLogger("trading_bot")

async def send_telegram_alert(message: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        logger.warning("TELEGRAM_CONFIG_MISSING | Token or Chat ID not found in environment variables.")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }

    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(url, json=payload, timeout=10.0)
            if res.status_code == 200:
                logger.info("TELEGRAM_NOTIFICATION_SENT | Success")
            else:
                logger.error(f"TELEGRAM_ERROR | Status: {res.status_code}, Body: {res.text}")
    except Exception as e:
        logger.error(f"TELEGRAM_EXCEPTION | {e}")
