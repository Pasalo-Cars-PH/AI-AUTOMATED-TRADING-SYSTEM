import asyncio
import logging
from datetime import datetime, timezone
from app.market.service import market_service
from app.strategy.evaluator import strategy_evaluator
from app.paper.account import paper_account
from app.notifications.telegram import send_telegram_message, IS_ENGINE_PAUSED

logger = logging.getLogger("trading_bot")

SYMBOLS_TO_MONITOR = ["BTCUSD", "XAUUSD", "EURUSD", "ETHUSD", "SOLUSD"]

class MarketScheduler:
    def __init__(self):
        self.is_running = False
        self.last_heartbeat = None

    async def start(self):
        if self.is_running:
            return
        self.is_running = True
        logger.info("MARKET_SCHEDULER_STARTING | Initializing loop...")
        asyncio.create_task(self._loop())

    async def _loop(self):
        while self.is_running:
            self.last_heartbeat = datetime.now(timezone.utc).isoformat()
            logger.info(f"MARKET_SCHEDULER_CYCLE | Heartbeat: {self.last_heartbeat}")

            if IS_ENGINE_PAUSED:
                logger.info("MARKET_SCHEDULER_PAUSED | Loop is paused via Telegram control.")
                await asyncio.sleep(60)
                continue

            # 1. Update Open Position Trailing & SL/TP Hit Detection
            for pos_id, pos in list(paper_account.open_positions.items()):
                try:
                    candles = await market_service.get_candles(pos.symbol, timeframe="M5")
                    if candles:
                        current_price = candles[-1].close if hasattr(candles[-1], 'close') else candles[-1]["close"]
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
                except Exception as e:
                    logger.error(f"MARKET_SYMBOL_FAILED | Position Check Failed for {pos.symbol}: {e}")

            # 2. Per-Symbol Isolated Market Data Update & Strategy Evaluation
            for symbol in SYMBOLS_TO_MONITOR:
                try:
                    # Isolated update per symbol
                    success = await market_service.update_symbol_data(symbol, timeframe="M5")
                    if not success:
                        logger.warning(f"MARKET_SYMBOL_FAILED | Could not update data for {symbol}, isolating and continuing...")
                        continue

                    candles = await market_service.get_candles(symbol, timeframe="M5")
                    if not candles:
                        logger.warning(f"MARKET_DATA_UNAVAILABLE | No cached candles for {symbol}")
                        continue

                    analysis = strategy_evaluator.evaluate_m5_setup(symbol, candles)
                    action = analysis.get("action")
                    score = analysis.get("score", 0)

                    if action in ["BUY", "SELL"] and score >= 70:
                        # FIX: Kunin ang latest_price mula sa huling saradong candle nang ligtas
                        latest_candle = candles[-1]
                        latest_price = latest_candle.close if hasattr(latest_candle, 'close') else latest_candle["close"]
                        
                        trade_params = analysis.get("trade_parameters", {})
                        sl = trade_params.get("stop_loss", 0.0)
                        tp = trade_params.get("take_profit", 0.0)
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
                            logger.info(f"PAPER_TRADE_EXECUTED | {action} {symbol} @ {latest_price}")
                        else:
                            logger.info(f"PAPER_TRADE_REJECTED | {symbol} - {reason}")

                except Exception as symbol_err:
                    # PER-SYMBOL ISOLATION: Error in one symbol does NOT crash scheduler loop
                    logger.error(f"MARKET_SYMBOL_FAILED | Error processing {symbol}: {symbol_err}", exc_info=True)

            await asyncio.sleep(60)

market_scheduler = MarketScheduler()
