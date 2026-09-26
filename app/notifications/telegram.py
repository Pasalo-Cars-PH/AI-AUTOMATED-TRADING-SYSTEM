import os
import httpx
import logging
from app.market.service import market_service
from app.strategy.evaluator import strategy_evaluator
from app.paper.account import paper_account

logger = logging.getLogger("trading_bot")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Global flag para sa Pause/Resume functionality
IS_ENGINE_PAUSED = False

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
    global IS_ENGINE_PAUSED
    message = data.get("message", {})
    text = message.get("text", "").strip()
    chat_id = str(message.get("chat", {}).get("id", ""))

    if not text or not chat_id:
        return

    parts = text.split()
    command = parts[0].lower()

    if command == "/start":
        msg = (
            "🤖 <b>AI Automated Trading System V2</b>\n\n"
            "Active Commands:\n"
            "• /signals — Live confluence scores\n"
            "• /status — Account overview & stats\n"
            "• /positions — Active open positions\n"
            "• /trades — Last 5 closed trades\n"
            "• /analyze &lt;SYMBOL&gt; — Deep analysis (e.g. <code>/analyze BTCUSD</code>)\n"
            "• /pause — Pause automated trade execution\n"
            "• /resume — Resume automated trade execution\n"
            "• /closeall — Emergency close all positions"
        )
        await send_telegram_message(msg, chat_id)

    elif command == "/signals":
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

    elif command == "/status":
        engine_state = "PAUSED ⏸️" if IS_ENGINE_PAUSED else "RUNNING 🟢"
        status_msg = (
            f"📊 <b>Paper Account Status</b>\n\n"
            f"<b>Engine State:</b> {engine_state}\n"
            f"<b>Balance:</b> ${paper_account.balance:,.2f}\n"
            f"<b>Equity:</b> ${paper_account.equity:,.2f}\n"
            f"<b>Open Positions:</b> {len(paper_account.open_positions)}\n"
            f"<b>Consecutive Losses:</b> {paper_account.consecutive_losses}"
        )
        await send_telegram_message(status_msg, chat_id)

    elif command == "/positions":
        if not paper_account.open_positions:
            await send_telegram_message("📂 <b>No open paper positions.</b>", chat_id)
            return

        msg = "📈 <b>Active Paper Positions</b>\n\n"
        for pos in paper_account.open_positions.values():
            pnl_emoji = "🟩" if pos.unrealized_pnl >= 0 else "🟥"
            msg += (
                f"• <b>{pos.symbol}</b> ({pos.direction})\n"
                f"  Entry: ${pos.simulated_entry:,.2f} | Current: ${pos.current_price:,.2f}\n"
                f"  SL: ${pos.stop_loss:,.2f} | TP: ${pos.take_profit:,.2f}\n"
                f"  Unrealized PnL: {pnl_emoji} ${pos.unrealized_pnl:,.2f}\n\n"
            )
        await send_telegram_message(msg, chat_id)

    elif command == "/trades":
        trades = paper_account.closed_positions[-5:]  # Get last 5 trades
        if not trades:
            await send_telegram_message("📋 <b>No trade history available yet.</b>", chat_id)
            return

        msg = "📜 <b>Last 5 Closed Trades</b>\n\n"
        for t in reversed(trades):
            res_emoji = "✅ WIN" if t.realized_pnl > 0 else "❌ LOSS"
            msg += (
                f"• <b>{t.symbol}</b> ({t.direction}) — {res_emoji}\n"
                f"  PnL: ${t.realized_pnl:,.2f} | Reason: {t.exit_reason}\n"
                f"  Exit Price: ${t.exit_price:,.2f}\n\n"
            )
        await send_telegram_message(msg, chat_id)

    elif command == "/analyze":
        if len(parts) < 2:
            await send_telegram_message("⚠️ Usage: <code>/analyze BTCUSD</code>", chat_id)
            return

        symbol = parts[1].upper()
        candles = market_service.get_candles(symbol, timeframe="M5")
        if not candles:
            await send_telegram_message(f"⚠️ No candle data found for <b>{symbol}</b>.", chat_id)
            return

        analysis = strategy_evaluator.evaluate_m5_setup(symbol, candles)
        ind = analysis["indicators"]
        reasons_text = "\n".join([f"• {r}" for r in analysis["reasons"]])

        msg = (
            f"🔍 <b>Deep Analysis for {symbol} (M5)</b>\n\n"
            f"<b>Action:</b> {analysis['action']}\n"
            f"<b>Confluence Score:</b> {analysis['score']}/100\n"
            f"<b>Latest Price:</b> ${analysis['latest_price']:,.2f}\n\n"
            f"<b>Technical Indicators:</b>\n"
            f"• EMA20: ${ind['ema_20']:,.2f}\n"
            f"• EMA50: ${ind['ema_50']:,.2f}\n"
            f"• RSI (14): {ind['rsi_14']}\n"
            f"• ATR (14): ${ind['atr_14']:,.2f}\n\n"
            f"<b>Score Breakdown:</b>\n{reasons_text}"
        )
        await send_telegram_message(msg, chat_id)

    elif command == "/pause":
        IS_ENGINE_PAUSED = True
        await send_telegram_message("⏸️ <b>Automated Trading Loop PAUSED.</b> No new trades will be opened.", chat_id)

    elif command == "/resume":
        IS_ENGINE_PAUSED = False
        await send_telegram_message("🟢 <b>Automated Trading Loop RESUMED.</b> Active scanning enabled.", chat_id)

    elif command == "/closeall":
        count = len(paper_account.open_positions)
        if count == 0:
            await send_telegram_message("ℹ️ No open positions to close.", chat_id)
            return

        for pos_id, pos in list(paper_account.open_positions.items()):
            paper_account.close_position(pos_id, pos.current_price, "MANUAL_TELEGRAM_CLOSE")

        await send_telegram_message(f"🚨 <b>EMERGENCY CLOSE:</b> All {count} position(s) closed at market price.", chat_id)
