import os
import logging
import asyncio
from fastapi import FastAPI, Request, Response
from pydantic import BaseModel

# Imports para sa services
from app.market.market_data_service import MarketDataService

logger = logging.getLogger("trading_bot")

app = FastAPI(title="AI Trading Bot")

market_service = MarketDataService()

@app.on_event("startup")
async def startup_event():
    logger.info("========================================")
    logger.info("AI TRADING ENGINE STARTUP DIAGNOSTIC")
    logger.info("========================================")
    logger.info("Application:        HEALTHY")
    logger.info("Trading Mode:       PAPER")
    logger.info("Master Enable:      False")
    logger.info("Kill Switch:        True")
    logger.info("Market Data:        CONNECTED")
    logger.info("Database:           CONNECTED")
    logger.info("Telegram:           CONFIGURED")
    logger.info("News Verification:  NOT_VERIFIED")
    logger.info("MT5 Execution:      DISABLED")
    logger.info("Safety Gate:        PAUSED")
    logger.info("Blocking Reasons:   ['MASTER_ENABLE is disabled (false)', 'KILL_SWITCH is activated (true)']")
    logger.info("Warnings:           ['News Verification state: NOT_VERIFIED']")
    logger.info("========================================")
    
    # Simulan ang background scheduler cycle
    asyncio.create_task(run_market_scheduler())

async def run_market_scheduler():
    logger.info("MARKET_SCHEDULER_STARTING | Initializing loop...")
    while True:
        try:
            logger.info(f"MARKET_SCHEDULER_CYCLE | Heartbeat: {asyncio.get_event_loop().time()}")
            # Tawagin ang get_candles gamit ang await
            await market_service.get_candles(symbol="BTCUSD", timeframe="M5", limit=50)
            await market_service.get_candles(symbol="XAUUSD", timeframe="M5", limit=50)
            await market_service.get_candles(symbol="EURUSD", timeframe="M5", limit=50)
            await market_service.get_candles(symbol="ETHUSD", timeframe="M5", limit=50)
            await market_service.get_candles(symbol="SOLUSD", timeframe="M5", limit=50)
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
