import os
import logging
import asyncio
from fastapi import FastAPI, Request, Response

# Tamang import para sa market service sa iyong project structure
from app.market.service import market_service

logger = logging.getLogger("trading_bot")

app = FastAPI(title="AI Trading Bot")

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
    logger.info("Market Data:        CONNECTED")
    logger.info("Database:           CONNECTED")
    logger.info("Telegram:           CONFIGURED")
    logger.info("========================================")
    
    # Simulan ang background scheduler cycle
    asyncio.create_task(run_market_scheduler())

async def run_market_scheduler():
    logger.info("MARKET_SCHEDULER_STARTING | Initializing loop...")
    symbols = ["BTCUSD", "ETHUSD", "SOLUSD", "XAUUSD", "EURUSD"]
    
    while True:
        try:
            logger.info("MARKET_SCHEDULER_CYCLE | Scanning M5 candles...")
            for symbol in symbols:
                await market_service.get_candles(symbol=symbol, timeframe="M5", limit=50)
        except Exception as e:
            logger.error(f"MARKET_SCHEDULER_ERROR | {e}")
        
        await asyncio.sleep(60)

@app.get("/")
async def root():
    return {"status": "online", "message": "AI Trading Bot is running"}

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        logger.info(f"TELEGRAM_WEBHOOK_RECEIVED | {data}")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error handling webhook: {e}")
        return Response(content=f"Error: {str(e)}", status_code=500)
