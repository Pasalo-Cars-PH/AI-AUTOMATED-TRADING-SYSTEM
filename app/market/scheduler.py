import asyncio
import logging
from app.market.service import market_service
from app.strategy.evaluator import strategy_evaluator
from app.paper.account import paper_account

logger = logging.getLogger("trading_bot")

SYMBOLS_TO_MONITOR = ["BTCUSD", "ETHUSD", "SOLUSD"]

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
                            
                            trade, reason = paper_account.open_position(
                                symbol=symbol,
                                side=action,
                                entry_price=latest_price,
                                stop_loss=sl,
                                take_profit=tp,
                                strategy="M5_CONFLUENCE_V1",
                                confluence_score=score,
                                reasons=analysis["reasons"]
                            )
                            
                            if trade:
                                logger.info(f"PAPER TRADE EXECUTED: {action} {symbol} @ {latest_price} (Score: {score})")
                            else:
                                logger.info(f"PAPER TRADE REJECTED: {symbol} - {reason}")
                
            except Exception as e:
                logger.error(f"Error in market scheduler loop: {e}", exc_info=True)
                
            await asyncio.sleep(60)

market_scheduler = MarketScheduler()
