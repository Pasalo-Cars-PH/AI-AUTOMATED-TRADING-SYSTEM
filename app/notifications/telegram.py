import os
import httpx
import logging

logger = logging.getLogger("trading_bot")

async def send_rich_telegram_alert(eval_result: dict):
    """
    Formats strategy evaluation into an upgraded HTML Telegram alert card 
    including TP/SL targets, H1 trend alignment, and ATR metrics.
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        logger.warning("TELEGRAM_CONFIG_MISSING | Telegram alerts disabled.")
        return False

    signal = eval_result.get("signal", "NEUTRAL")
    symbol = eval_result.get("symbol", "N/A")
    timeframe = eval_result.get("timeframe", "M5")
    price = eval_result.get("price", 0.0)
    score = eval_result.get("score", 0)
    tp = eval_result.get("tp_price", 0.0)
    sl = eval_result.get("sl_price", 0.0)
    h1_trend = eval_result.get("h1_trend", "N/A")
    metrics = eval_result.get("metrics", {})

    emoji = "🚨🟢" if signal == "BUY" else "🚨🔴"
    
    # Upgraded HTML Formatted Telegram Message
    message = f"""
<b>{emoji} AI TRADING ALERT: {signal}</b>
━━━━━━━━━━━━━━━━━━
<b>Symbol:</b> <code>{symbol}</code>
<b>Timeframe:</b> {timeframe} | <b>H1 Trend:</b> {h1_trend}
<b>Entry Price:</b> ${price:,.2f}

<b>🎯 Take Profit (TP):</b> ${tp:,.2f}
<b>🛡 Stop Loss (SL):</b> ${sl:,.2f}

<b>📊 Confluence Score:</b> {score}/100

<b>📈 Technical Metrics:</b>
• <b>RSI (14):</b> {metrics.get('rsi', 'N/A')}
• <b>ATR (14):</b> {metrics.get('atr', 'N/A')}
• <b>EMA (20/50):</b> {metrics.get('ema20', 'N/A')} / {metrics.get('ema50', 'N/A')}

<b>🛡 Safety Mode:</b> PAPER TRADING ONLY (Logged)
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
