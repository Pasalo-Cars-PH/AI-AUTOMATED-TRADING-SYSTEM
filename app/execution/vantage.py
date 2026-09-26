import os
import httpx
import logging

logger = logging.getLogger("trading_bot")

# Ang Webhook URL ng iyong EA o ngrok/bridge listener
WEBHOOK_URL = os.getenv("VANTAGE_WEBHOOK_URL") 
WEBHOOK_PASSCODE = os.getenv("WEBHOOK_PASSCODE", "MySecretVantageKey123")

async def execute_vantage_trade(symbol: str, action: str, lot_size: float, sl: float, tp: float):
    """
    Executes trades directly via free Webhook EA on Vantage MT4/MT5.
    No monthly cloud gateway fees required.
    """
    if not WEBHOOK_URL:
        logger.warning("VANTAGE_WEBHOOK_URL is not set. Skipping execution.")
        return False

    clean_symbol = symbol.replace("=X", "").replace("USDT", "USD")

    payload = {
        "passcode": WEBHOOK_PASSCODE,
        "action": action.upper(),  # "BUY" or "SELL"
        "symbol": clean_symbol,
        "volume": lot_size,
        "sl": sl,
        "tp": tp,
        "magic": 888111
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(WEBHOOK_URL, json=payload, timeout=5.0)
            if resp.status_code == 200:
                logger.info(f"FREE_WEBHOOK_EXECUTION_OK | {action} {clean_symbol} | Lot: {lot_size}")
                return True
            else:
                logger.error(f"FREE_WEBHOOK_EXECUTION_FAILED | Status: {resp.status_code} | {resp.text}")
                return False
    except Exception as e:
        logger.error(f"FREE_WEBHOOK_CONNECTION_ERROR | Error: {e}")
        return False
