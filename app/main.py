import os
import logging
import asyncio
from fastapi import FastAPI, Request, Response

from app.market.scheduler import market_scheduler

# Siguraduhing naka-configure ang logging para mag-stream sa Render stdout/console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("trading_bot")
logger.setLevel(logging.INFO)

app = FastAPI(title="AI Trading Bot Engine")

@app.on_event("startup")
async def startup_event():
    master_enable = os.getenv("MASTER_ENABLE", "false").lower() == "true"
    kill_switch = os.getenv("KILL_SWITCH", "true").lower() == "true"
    trading_mode = os.getenv("TRADING_MODE", "PAPER")

    logger.info("MARKET_DATA_SERVICE_READY")
    logger.info("MARKET_PROVIDER_ROUTING_READY")
    logger.info("MARKET_SCHEDULER_STARTING")
    logger.info(f"Trading Mode: {trading_mode} | Master Enable: {master_enable} | Kill Switch: {kill_switch}")
    
    # Paandarin ang nag-iisang canonical scheduler instance
    asyncio.create_task(market_scheduler.start())

@app.get("/")
async def root():
    return {"status": "online", "message": "AI Trading Bot Canonical Engine Active"}

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "market_data_and_alert_engine"}

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        return {"status": "ok"}
    except Exception as e:
        return Response(content=f"Error: {str(e)}", status_code=500)
