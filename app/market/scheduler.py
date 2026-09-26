import asyncio
import logging
from app.market.service import market_service
from app.strategy.evaluator import strategy_evaluator
from app.paper.account import paper_account
from app.notifications.telegram import send_telegram_message, IS_ENGINE_PAUSED

logger = logging.getLogger("trading_bot")

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

                # 1. Check & Auto-Close Existing Positions hit by SL/TP
                for pos_id, pos in list(paper_account.open_positions.items()):
                    latest_candles = market_service.get_candles(pos.symbol, timeframe="M5")
                    if latest_candles:
                        current_price = latest_candles[-1]["close"]
                        closed_trade = paper_account.update_position_price(pos_id, current_price)
                        if closed_trade:
                            res_emoji = "🎯 TAKE PROFIT HIT" if closed_trade.realized_pnl > 0 else "🛑 STOP LOSS HIT"
                            close_msg = (
                                f"<b>{res_emoji}</b>\n\n"
                                f"<b>Symbol:</b> {closed_trade.symbol}\n"
                                f"<b>Direction:</b> {closed_trade.direction}\n"
                                f"<b>PnL:</b> ${closed_trade.realized_pnl:,.2f}\n"
                                f"<b>Exit Price:</b> ${closed_trade.exit_price:,.2f}\n"
                                f"<b>Reason:</b> {closed_trade.exit_reason}"
                            )
                            await send_telegram_message(close_msg)

                # 2. Monitor & Evaluate Market Setups
                for symbol in SYMBOLS_TO_MONITOR:
                    await market_service.update_symbol_data(symbol, timeframe="M5")
                    
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
