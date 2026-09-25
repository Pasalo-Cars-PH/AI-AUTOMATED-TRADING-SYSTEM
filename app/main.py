import logging
import datetime
from typing import Optional

from fastapi import FastAPI, status, Query
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings, ApplicationStatus
from app.safety_gate import safety_gate
from app.paper.account import paper_account
from app.paper.analytics import PaperAnalytics
from app.market.router import router as market_router
from app.market.scheduler import market_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("trading_bot")

app = FastAPI(title=settings.APP_NAME, version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Market Data Router (/market/status, /market/quote, /market/candles)
app.include_router(market_router)

def print_startup_diagnostics(diag: dict):
    logger.info("========================================")
    logger.info("AI TRADING ENGINE STARTUP DIAGNOSTIC")
    logger.info("========================================")
    logger.info(f"Application:    {diag['application_status']}")
    logger.info(f"Trading Mode:   {diag['mode']}")
    logger.info(f"Master Enable:  {diag['checks']['MASTER_ENABLE']['value']}")
    logger.info(f"Kill Switch:    {diag['checks']['KILL_SWITCH']['value']}")
    logger.info(f"Market Data:    {diag['checks']['MARKET_DATA']['value']}")
    logger.info(f"Database:       {diag['checks']['DATABASE']['value']}")
    logger.info(f"Telegram:       {diag['checks']['TELEGRAM']['value']}")
    logger.info(f"News Verification: {diag['checks']['NEWS']['value']}")
    logger.info(f"MT5 Execution:  {diag['checks']['EXECUTION']['status']}")
    logger.info(f"Safety Gate:    {diag['trading_status']}")
    logger.info(f"Blocking Reasons: {diag['blocking_reasons']}")
    logger.info(f"Warnings:       {diag['warnings']}")
    logger.info("========================================")

@app.on_event("startup")
async def startup_event():
    telegram_status = "CONFIGURED" if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID else "MISCONFIGURED"
    diag = safety_gate.evaluate(telegram_status=telegram_status)
    print_startup_diagnostics(diag)
    # Start Live Market Data Background Loop
    await market_scheduler.start()

# Base Health & Status Endpoints
@app.get("/", status_code=status.HTTP_200_OK)
@app.head("/", status_code=status.HTTP_200_OK)
async def root():
    telegram_status = "CONFIGURED" if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID else "MISCONFIGURED"
    diag = safety_gate.evaluate(telegram_status=telegram_status)
    return {
        "service": settings.APP_NAME,
        "application_status": ApplicationStatus.HEALTHY.value,
        "trading_status": diag["trading_status"],
        "mode": settings.TRADING_MODE
    }

@app.get("/health", status_code=status.HTTP_200_OK)
@app.head("/health", status_code=status.HTTP_200_OK)
async def health():
    return {
        "status": "ok",
        "application_status": ApplicationStatus.HEALTHY.value,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z"
    }

@app.get("/status", status_code=status.HTTP_200_OK)
async def get_status():
    telegram_status = "CONFIGURED" if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID else "MISCONFIGURED"
    diag = safety_gate.evaluate(telegram_status=telegram_status)
    return {
        "engine": {
            "application_status": diag["application_status"],
            "trading_status": diag["trading_status"],
            "mode": diag["mode"]
        },
        "safety_gate": {
            "allowed": diag["overall_allowed"],
            "blocking_reasons": diag["blocking_reasons"],
            "warnings": diag["warnings"]
        },
        "market_data": {
            "provider": "binance",
            "status": diag["checks"]["MARKET_DATA"]["value"],
            "symbols_available": ["BTCUSD", "ETHUSD", "SOLUSD"]
        },
        "database": {
            "status": diag["checks"]["DATABASE"]["value"]
        },
        "telegram": {
            "status": diag["checks"]["TELEGRAM"]["value"]
        },
        "execution": diag["checks"]["EXECUTION"],
        "timestamp": diag["timestamp"]
    }

@app.get("/safety", status_code=status.HTTP_200_OK)
async def get_safety():
    telegram_status = "CONFIGURED" if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID else "MISCONFIGURED"
    return safety_gate.evaluate(telegram_status=telegram_status)

# Paper Trading Pipeline Endpoints
@app.get("/paper/status", status_code=status.HTTP_200_OK)
async def get_paper_status():
    summary = PaperAnalytics.get_performance_summary()
    daily_pnl = paper_account.equity - paper_account.daily_start_balance
    
    return {
        "mode": settings.TRADING_MODE,
        "real_order_submission": False,
        "balance": paper_account.balance,
        "equity": paper_account.equity,
        "daily_pnl": round(daily_pnl, 2),
        "open_positions": len(paper_account.open_positions),
        "open_risk": round(len(paper_account.open_positions) * paper_account.risk_per_trade * 100, 2),
        "trades_today": summary["total_trades"],
        "win_rate": summary["win_rate"],
        "profit_factor": summary["profit_factor"]
    }

@app.get("/paper/positions", status_code=status.HTTP_200_OK)
async def get_paper_positions():
    return {
        "count": len(paper_account.open_positions),
        "positions": list(paper_account.open_positions.values())
    }

@app.get("/paper/trades", status_code=status.HTTP_200_OK)
async def get_paper_trades(symbol: Optional[str] = Query(None), strategy: Optional[str] = Query(None)):
    trades = paper_account.closed_positions
    if symbol:
        trades = [t for t in trades if t.symbol.upper() == symbol.upper()]
    if strategy:
        trades = [t for t in trades if t.strategy.upper() == strategy.upper()]
        
    return {
        "count": len(trades),
        "trades": trades
    }

@app.get("/paper/no-trades", status_code=status.HTTP_200_OK)
async def get_no_trade_logs():
    return {
        "count": len(paper_account.no_trade_logs),
        "rejected_setups": paper_account.no_trade_logs
    }

@app.get("/paper/performance", status_code=status.HTTP_200_OK)
async def get_paper_performance():
    return PaperAnalytics.get_performance_summary()
