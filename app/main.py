import os
import logging
import asyncio
from datetime import datetime, timezone
import pandas as pd
from fastapi import FastAPI, Request, Response

from app.market.service import market_service
from app.strategy.evaluator import InstitutionalBoostedEvaluator
from app.notifications.telegram import send_telegram_alert

logger = logging.getLogger("trading_bot")

app = FastAPI(title="AI Trading Bot")
evaluator = InstitutionalBoostedEvaluator()

def is_forex_market_open() -> bool:
    """Sinisiyasat kung bukas ang Forex/Metals market (Lunes - Biyernes)"""
    weekday = datetime.now(timezone.utc).weekday()
    return weekday < 5  # 0 to 4 ay Monday to Friday (5 = Sabado, 6 = Linggo)

@app.on_event("startup")
async def startup_event():
    master_enable = os.getenv("MASTER_ENABLE", "false").lower() == "true"
    kill_switch = os.getenv("KILL_SWITCH", "true").lower() == "true"
    trading_mode = os.getenv("TRADING_MODE", "PAPER")

    logger.info("========================================")
    logger.info("AI TRADING ENGINE STARTUP DIAGNOSTIC")
    logger.info("========================================")
    logger.info(f"Application:        HEALTHY")
    logger.info(f"Trading Mode:       {trading_mode}")
    logger.info(f"Master Enable:      {master_enable}")
    logger.info(f"Kill Switch:        {kill_switch}")
    logger.info("Multi-TF Engine:    ACTIVE (M5, M15)")
    logger.info("========================================")
    
    asyncio.create_task(run_market_scheduler())

async def run_market_scheduler():
    logger.info("MARKET_SCHEDULER_STARTING | Initializing M5 & M15 Loop...")
    
    crypto_symbols = ["BTCUSD", "ETHUSD", "SOLUSD"]
    forex_symbols = ["XAUUSD", "EURUSD"]
    timeframes = ["M5", "M15"]
    
    while True:
        try:
            # Pagsasamahin ang Symbols batay sa Market Schedule
            active_symbols = crypto_symbols.copy()
            if is_forex_market_open():
                active_symbols.extend(forex_symbols)
            else:
                logger.debug("WEEKEND_MODE | Forex/Metals markets closed. Scanning Crypto 24/7 only.")

            for symbol in active_symbols:
                try:
                    # Fetch H1 trend candles
                    raw_h1 = await market_service.get_candles(symbol=symbol, timeframe="H1", limit=100)
                    if not raw_h1:
                        continue
                    df_h1 = pd.DataFrame(raw_h1) if isinstance(raw_h1, list) else raw_h1

                    for tf in timeframes:
                        raw_tf = await market_service.get_candles(symbol=symbol, timeframe=tf, limit=200)
                        if not raw_tf:
                            continue

                        df_tf = pd.DataFrame(raw_tf) if isinstance(raw_tf, list) else raw_tf

                        if df_tf is not None and not df_tf.empty:
                            analysis = evaluator.evaluate_signal(df_tf, df_h1)
                            
                            if analysis.get("signal") in ["BUY", "SELL"]:
                                signal_type = analysis["signal"]
                                score = analysis["score"]
                                price = analysis["price"]
                                sl = analysis["stop_loss"]
                                tp = analysis["take_profit"]
                                reasons = "\n• " + "\n• ".join(analysis["reasons"])

                                msg = (
                                    f"🚨 **INSTITUTIONAL SIGNAL DETECTED** 🚨\n\n"
                                    f"📌 **Symbol:** `{symbol}`\n"
                                    f"⏱ **Timeframe:** `{tf}`\n"
                                    f"🎯 **Action:** **{signal_type}**\n"
                                    f"📊 **Confluence Score:** `{score}`\n"
                                    f"💵 **Entry Price:** `{price}`\n"
                                    f"🛑 **Stop Loss:** `{sl}`\n"
                                    f"🎯 **Take Profit:** `{tp}`\n\n"
                                    f"🔍 **Confluence Reasons:**{reasons}\n\n"
                                    f"⚙️ **Mode:** `PAPER TRADING`"
                                )
                                logger.info(f"SIGNAL TRIGGERED | {symbol} {tf} {signal_type} | Score: {score}")
                                await send_telegram_alert(msg)

                except Exception as sym_err:
                    logger.warning(f"SYMBOL_SCAN_SKIPPED | {symbol} | Reason: {sym_err}")
                    continue
                                
        except Exception as e:
            logger.error(f"MARKET_SCHEDULER_ERROR | {e}")
        
        await asyncio.sleep(60)

@app.get("/")
async def root():
    return {"status": "online", "message": "AI Trading Bot M5/M15 Engine Active"}

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        return {"status": "ok"}
    except Exception as e:
        return Response(content=f"Error: {str(e)}", status_code=500)
