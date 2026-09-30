import os
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Import Telegram command handler
from app.telegram import handle_telegram_command

# Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main_app")

app = FastAPI(
    title="AI Trading Bot Engine",
    version="2.0.0",
    description="Execution Engine & Telegram Observability Layer"
)

# Global Mock/System State for Phase C Read-Only Observability
SYSTEM_STATE = {
    "mode": "PAPER",
    "master_enable": True,
    "kill_switch": False,
    "execution_lock": "ACTIVE"
}

DAILY_STATS = {
    "total_scans": 0,
    "candidate_setups": 0,
    "paper_executions": 0,
    "rejected_candidates": 0,
    "watch_candidates": 0,
    "scores": [],
    "rejection_breakdown": {},
    "last_scan_time": "N/A"
}

LAST_TRADE = None


# ---------------------------------------------------------
# HEALTH & KEEP-ALIVE ENDPOINTS (Supports GET & HEAD for UptimeRobot Free)
# ---------------------------------------------------------

@app.api_route("/", methods=["GET", "HEAD"])
def root_status():
    return {
        "status": "online",
        "service": "AI Trading Bot Engine",
        "version": "2.0.0",
        "execution_lock": "ACTIVE",
        "trading_mode": "READ_ONLY"
    }

@app.api_route("/health", methods=["GET", "HEAD"])
def health_check():
    return {
        "status": "ok",
        "telegram_observability": "active",
        "market_data_provider": "yfinance"
    }


# ---------------------------------------------------------
# TELEGRAM WEBHOOK ROUTE
# ---------------------------------------------------------

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        logger.info(f"Incoming Webhook Payload: {data}")
        
        result = handle_telegram_command(
            data=data,
            system_state=SYSTEM_STATE,
            daily_stats=DAILY_STATS,
            last_trade=LAST_TRADE
        )
        return JSONResponse(content=result, status_code=200)
    except Exception as e:
        logger.error(f"Error handling webhook: {e}")
        return JSONResponse(content={"status": "error", "message": str(e)}, status_code=500)


# ---------------------------------------------------------
# PAPER SCAN TEST ENDPOINT (Supports GET & HEAD)
# ---------------------------------------------------------

@app.api_route("/test-scan", methods=["GET", "HEAD"])
def trigger_test_scan(paper_test: bool = False):
    import datetime
    
    # Update Scan Stats
    DAILY_STATS["total_scans"] += 1
    DAILY_STATS["last_scan_time"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    
    if paper_test:
        DAILY_STATS["candidate_setups"] += 1
        DAILY_STATS["paper_executions"] += 1
        DAILY_STATS["scores"].append(82.0)
        
        global LAST_TRADE
        LAST_TRADE = {
            "symbol": "XAUUSD",
            "action": "BUY_PAPER",
            "entry": 2650.50,
            "sl": 2642.00,
            "tp": 2670.00,
            "score": 82.0,
            "timestamp": DAILY_STATS["last_scan_time"]
        }
        
        return {
            "status": "success",
            "message": "Paper scan completed successfully",
            "scan_time": DAILY_STATS["last_scan_time"],
            "mock_trade_logged": LAST_TRADE
        }

    return {
        "status": "success",
        "message": "Market scan performed. No setup criteria met.",
        "scan_time": DAILY_STATS["last_scan_time"],
        "total_scans_today": DAILY_STATS["total_scans"]
    }
