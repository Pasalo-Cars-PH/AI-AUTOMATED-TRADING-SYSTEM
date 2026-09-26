import os
import httpx
import logging

logger = logging.getLogger("trading_bot")

async def send_rich_telegram_alert(eval_result: dict):
    """
    Formats strategy evaluation into a structured Telegram alert card.
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        logger.warning("TELEGRAM_CONFIG_MISSING | Telegram alerts disabled.")
        return False

    signal = eval_result["signal"]
    symbol = eval_result["symbol"]
    timeframe = eval_result["timeframe"]
    price = eval_result["price"]
    score = eval_result["score"]
    metrics = eval_result["metrics"]

    emoji = "🚨🟢" if signal == "BUY" else "🚨🔴"
    
    # HTML Formatted Telegram Message
    message = f"""
<b>{emoji} AI TRADING ALERT: {signal}</b>
━━━━━━━━━━━━━━━━━━
<b>Symbol:</b> <code>{symbol}</code>
<b>Timeframe:</b> {timeframe}
<b>Entry Price:</b> ${price:,.2f}

<b>📊 Confluence Score:</b> {score}/100

<b>📈 Technical Metrics:</b>
• <b>RSI (14):</b> {metrics['rsi']}
• <b>EMA (20/50):</b> {metrics['ema20']} / {metrics['ema50']}
• <b>Bollinger Bands:</b> [{metrics['bb_lower']} - {metrics['bb_upper']}]

<b>🛡 Safety Mode:</b> PAPER TRADING ONLY
"""

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message.strip(),
        "parse_mode": "HTML"
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(url, json=payload)
            if res.status_code == 200:
                logger.info(f"TELEGRAM_ALERT_SENT | {symbol} {signal}")
                return True
            else:
                logger.error(f"TELEGRAM_SEND_FAILED | Status: {res.status_code}")
                return False
    except Exception as e:
        logger.error(f"TELEGRAM_EXCEPTION | {str(e)}")
        return False
