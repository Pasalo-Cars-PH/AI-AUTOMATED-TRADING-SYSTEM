import asyncio
import logging
from app.market.service import market_service
from app.strategy.evaluator import strategy_evaluator
from app.paper.account import paper_account
from app.notifications.telegram import send_telegram_message, IS_ENGINE_PAUSED

logger = logging.getLogger("trading_bot")

# Kasama na ang Gold (XAUUSD=X) at EUR/USD (EURUSD=X)
SYMBOLS_TO_MONITOR = ["BTCUSD", "XAUUSD=X", "EURUSD=X", "ETHUSD", "SOLUSD"]

class MarketScheduler:
    def __init__(self):
        self.is_running = False

    async def start(self):
        if self.is_running:
            return
        self.is_running = True
        logger.info("Starting Market Data Loop & Automated Strategy Execution...")
        asyncio.create_task(self._loop())

    async def _loop(self):
        while self.is_running:
            try:
                # 0. Check kung paused ang engine sa Telegram
                if IS_ENGINE_PAUSED:
                    logger.info("Market Scheduler loop is PAUSED. Skipping evaluation...")
                    await asyncio.sleep(60)
                    continue

                for symbol in SYMBOLS_TO_MONITOR:
                    # 1. Fetch & Update Candle Data
                    await market_service.update_symbol_data(symbol, timeframe="M5")
                    
                    # 2. Analyze Strategy Setup
                    candles = market_service.get_candles(symbol, timeframe="M5")
                    if candles:
                        analysis = strategy_evaluator.evaluate_m5_setup(symbol, candles)
                        action = analysis.get("action")
                        score = analysis.get("score", 0)
                        
                        # 3. Auto-Execute Trade on High Confluence (>= 70)
                        if action in ["BUY", "SELL"] and score >= 70:
                            latest_price = analysis["latest_price"]
                            sl = analysis["trade_parameters"]["stop_loss"]
                            tp = analysis["trade_parameters"]["take_profit"]
                            reasons_list = analysis.get("reasons", [])
                            reasons_text = "\n".join([f"• {r}" for r in reasons_list])
                            
                            trade, reason = paper_account.open_position(
                                symbol=symbol,
                                side=action,
                                entry_price=latest_price,
                                stop_loss=sl,
                                take_profit=tp,
                                strategy="M5_CONFLUENCE_V1",
                                confluence_score=score,
                                reasons=reasons_list
                            )
                            
                            if trade:
                                alert_msg = (
                                    f"🚀 <b>PAPER TRADE EXECUTED</b>\n\n"
                                    f"<b>Symbol:</b> {symbol}\n"
                                    f"<b>Action:</b> {action}\n"
                                    f"<b>Entry Price:</b> ${latest_price:,.2f}\n"
                                    f"<b>Stop Loss:</b> ${sl:,.2f}\n"
                                    f"<b>Take Profit:</b> ${tp:,.2f}\n"
                                    f"<b>Confluence Score:</b> {score}/100\n\n"
                                    f"<b>Reasons:</b>\n{reasons_text}"
                                )
                                await send_telegram_message(alert_msg)
                                logger.info(f"PAPER TRADE EXECUTED: {action} {symbol} @ {latest_price}")
                            else:
                                logger.info(f"PAPER TRADE REJECTED: {symbol} - {reason}")
                
            except Exception as e:
                logger.error(f"Error in market scheduler loop: {e}", exc_info=True)
                
            await asyncio.sleep(60)

market_scheduler = MarketScheduler()
