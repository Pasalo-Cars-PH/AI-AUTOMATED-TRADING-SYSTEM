import os
import logging
import datetime
import yfinance as yf
from typing import Optional, Dict, Any
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Import Telegram command handler & sender
from app.telegram import handle_telegram_command, send_telegram_reply

# Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main_app")

app = FastAPI(
    title="AI Trading Bot Engine",
    version="2.0.0",
    description="Execution Engine & Telegram Observability Layer"
)

# SYMBOL MAPPING
SYMBOL_MAP = {
    "XAUUSD": "GC=F",      # Gold Futures / Spot Proxy
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "JPY=X",
    "BTCUSD": "BTC-USD"
}

# Global Memory State for Phase C Read-Only Observability
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


def fetch_live_price(symbol: str) -> Optional[float]:
    """
    Fetches real-time market price using yfinance.
    """
    yf_ticker = SYMBOL_MAP.get(symbol, symbol)
    try:
        ticker = yf.Ticker(yf_ticker)
        fast_info = getattr(ticker, 'fast_info', None)
        if fast_info and 'lastPrice' in fast_info and fast_info['lastPrice']:
            return round(float(fast_info['lastPrice']), 2)
        
        hist = ticker.history(period="1d", interval="1m")
        if not hist.empty:
            return round(float(hist['Close'].iloc[-1]), 2)
    except Exception as e:
        logger.error(f"Error fetching live price for {symbol}: {e}")
    return None


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
# REAL-TIME SYNCHRONOUS PAPER SCAN ENDPOINT (Supports GET & HEAD)
# ---------------------------------------------------------

@app.api_route("/test-scan", methods=["GET", "HEAD"])
def trigger_test_scan(paper_test: bool = False, symbol: str = "XAUUSD"):
    """
    Synchronous Real-Time Scan: Instantly fetches live market price and returns execution details.
    """
    global LAST_TRADE
    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    
    DAILY_STATS["total_scans"] += 1
    DAILY_STATS["last_scan_time"] = now_utc
    
    # Live market price fetch
    live_price = fetch_live_price(symbol)
    if not live_price:
        live_price = 4155.50 if symbol == "XAUUSD" else 1.0000

    trade_details = None

    if paper_test:
        sl_price = round(live_price - 10.0, 2)
        tp_price = round(live_price + 20.0, 2)
        score = 82.0

        DAILY_STATS["candidate_setups"] += 1
        DAILY_STATS["paper_executions"] += 1
        DAILY_STATS["scores"].append(score)

        trade_details = {
            "symbol": symbol,
            "action": "BUY_PAPER",
            "entry": live_price,
            "sl": sl_price,
            "tp": tp_price,
            "score": score,
            "timestamp": now_utc
        }
        LAST_TRADE = trade_details

        # Send Telegram alert broadcast
        admin_chat_id = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")[0].strip()
        if admin_chat_id:
            alert_msg = (
                "🧪 *REAL-TIME PAPER EXECUTION LOGGED*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"• Symbol: `{symbol}`\n"
                f"• Action: `BUY_PAPER`\n"
                f"• Live Entry: `${live_price}`\n"
                f"• Stop Loss: `${sl_price}`\n"
                f"• Take Profit: `${tp_price}`\n"
                f"• Confluence Score: `{score}/100`\n"
                f"• Execution Lock: 🔒 *READ-ONLY*\n"
                f"• Timestamp: `{now_utc}`"
            )
            send_telegram_reply(admin_chat_id, alert_msg)

    return {
        "status": "success",
        "paper_test_mode": paper_test,
        "symbol_scanned": symbol,
        "fetched_live_price": live_price,
        "logged_trade": trade_details,
        "scan_time": now_utc
    }
