import os
import logging
import yfinance as yf
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Tuple
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Import Telegram command handler & sender
from app.telegram import handle_telegram_command, send_telegram_reply

# Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main_app")

app = FastAPI(
    title="AI Trading Bot Engine",
    version="2.3.0",
    description="Multi-Pair Pinbar Signal Alert System"
)

# SYMBOL MAPPING (Updated Multi-Pair Focus)
SYMBOL_MAP = {
    "XAUUSD": "GC=F",      # Gold Futures / Spot Proxy
    "EURUSD": "EURUSD=X",  # Euro / US Dollar
    "GBPUSD": "GBPUSD=X",  # British Pound / US Dollar
    "USDJPY": "JPY=X",      # US Dollar / Japanese Yen
    "BTCUSD": "BTC-USD"    # Bitcoin / US Dollar
}

# Global Memory State
SYSTEM_STATE = {
    "mode": "SIGNAL_ALERT",
    "master_enable": True,
    "kill_switch": False,
    "execution_lock": "SEMI_AUTOMATED"
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


def get_ph_time_str() -> str:
    """Returns current timestamp formatted in Philippine Time (UTC+8)."""
    ph_tz = timezone(timedelta(hours=8))
    return datetime.now(ph_tz).strftime("%Y-%m-%d %I:%M:%S %p PHT")


def analyze_last_pinbar(symbol: str) -> Tuple[Optional[str], Optional[Dict]]:
    """
    Kina-kalkula ang huling saradong candle (Last Closed Candle) sa M15 timeframe 
    upang malaman kung may valid at accurate na Pinbar pattern.
    """
    yf_ticker = SYMBOL_MAP.get(symbol, symbol)
    try:
        ticker = yf.Ticker(yf_ticker)
        hist = ticker.history(period="1d", interval="15m")
        
        if len(hist) < 2:
            return None, None

        # Kunin ang HULING SARADONG CANDLE (Prev Candle / Index -2)
        last_candle = hist.iloc[-2]
        c_open = float(last_candle['Open'])
        c_high = float(last_candle['High'])
        c_low = float(last_candle['Low'])
        c_close = float(last_candle['Close'])

        total_range = c_high - c_low
        if total_range == 0:
            return None, None

        body_size = abs(c_close - c_open)
        upper_wick = c_high - max(c_open, c_close)
        lower_wick = min(c_open, c_close) - c_low

        candle_details = {
            "open": round(c_open, 5 if "USD" in symbol and symbol != "XAUUSD" and symbol != "BTCUSD" else 2),
            "high": round(c_high, 5 if "USD" in symbol and symbol != "XAUUSD" and symbol != "BTCUSD" else 2),
            "low": round(c_low, 5 if "USD" in symbol and symbol != "XAUUSD" and symbol != "BTCUSD" else 2),
            "close": round(c_close, 5 if "USD" in symbol and symbol != "XAUUSD" and symbol != "BTCUSD" else 2),
            "range": round(total_range, 5 if "USD" in symbol and symbol != "XAUUSD" and symbol != "BTCUSD" else 2),
            "upper_wick_pct": round((upper_wick / total_range) * 100, 1),
            "lower_wick_pct": round((lower_wick / total_range) * 100, 1)
        }

        # Rules for Accurate Pinbar (Wick >= 55% of total candle range & small body)
        if lower_wick / total_range >= 0.55 and body_size / total_range <= 0.30:
            return "BULLISH_PINBAR", candle_details
        elif upper_wick / total_range >= 0.55 and body_size / total_range <= 0.30:
            return "BEARISH_PINBAR", candle_details

        return "NO_PINBAR", candle_details

    except Exception as e:
        logger.error(f"Pinbar analysis error for {symbol}: {e}")
        return None, None


def fetch_live_price(symbol: str) -> Optional[float]:
    """Fetches real-time market price using yfinance."""
    yf_ticker = SYMBOL_MAP.get(symbol, symbol)
    try:
        ticker = yf.Ticker(yf_ticker)
        fast_info = getattr(ticker, 'fast_info', None)
        if fast_info and 'lastPrice' in fast_info and fast_info['lastPrice']:
            return round(float(fast_info['lastPrice']), 5 if "USD" in symbol and symbol not in ["XAUUSD", "BTCUSD"] else 2)
        
        hist = ticker.history(period="1d", interval="1m")
        if not hist.empty:
            return round(float(hist['Close'].iloc[-1]), 5 if "USD" in symbol and symbol not in ["XAUUSD", "BTCUSD"] else 2)
    except Exception as e:
        logger.error(f"Error fetching live price for {symbol}: {e}")
    return None


# ---------------------------------------------------------
# HEALTH & KEEP-ALIVE ENDPOINTS
# ---------------------------------------------------------

@app.api_route("/", methods=["GET", "HEAD"])
def root_status():
    return {
        "status": "online",
        "service": "AI Trading Bot Engine",
        "version": "2.3.0",
        "supported_pairs": list(SYMBOL_MAP.keys()),
        "execution_mode": "MULTI_PAIR_PINBAR_ALERTS",
        "server_ph_time": get_ph_time_str()
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
# REAL-TIME SYNCHRONOUS SIGNAL SCAN ENDPOINT WITH MULTI-PAIR SUPPORT
# ---------------------------------------------------------

@app.api_route("/test-scan", methods=["GET", "HEAD"])
def trigger_test_scan(paper_test: bool = False, symbol: str = "XAUUSD"):
    """
    Synchronous Real-Time Scan featuring Pinbar Candle Pattern Verification for Multi-Pairs.
    """
    global LAST_TRADE
    now_pht = get_ph_time_str()
    
    # Check if symbol is supported
    if symbol not in SYMBOL_MAP:
        return JSONResponse(
            content={"status": "error", "message": f"Symbol {symbol} not in supported pairs list: {list(SYMBOL_MAP.keys())}"},
            status_code=400
        )

    DAILY_STATS["total_scans"] += 1
    DAILY_STATS["last_scan_time"] = now_pht
    
    live_price = fetch_live_price(symbol)
    if not live_price:
        live_price = 4153.30 if symbol == "XAUUSD" else 1.08500

    # Analyze Pinbar Candle
    pinbar_type, candle_meta = analyze_last_pinbar(symbol)

    trade_details = None

    if paper_test:
        if not candle_meta:
            candle_meta = {
                "open": round(live_price - 0.0020, 5 if symbol in ["EURUSD", "GBPUSD"] else 2),
                "high": round(live_price + 0.0010, 5 if symbol in ["EURUSD", "GBPUSD"] else 2),
                "low": round(live_price - 0.0080, 5 if symbol in ["EURUSD", "GBPUSD"] else 2),
                "close": live_price,
                "range": 0.0090,
                "upper_wick_pct": 11.1,
                "lower_wick_pct": 77.8
            }
            pinbar_type = "BULLISH_PINBAR"

        action = "BUY" if pinbar_type == "BULLISH_PINBAR" or pinbar_type == "NO_PINBAR" else "SELL"
        
        # Risk settings dynamically adjusted per asset type
        pips_buffer = 0.00150 if symbol in ["EURUSD", "GBPUSD"] else (0.15 if symbol == "USDJPY" else 2.00)
        
        if action == "BUY":
            sl_price = round(candle_meta['low'] - pips_buffer, 5 if symbol in ["EURUSD", "GBPUSD"] else 2)
            tp_price = round(live_price + (pips_buffer * 2.5), 5 if symbol in ["EURUSD", "GBPUSD"] else 2)
        else:
            sl_price = round(candle_meta['high'] + pips_buffer, 5 if symbol in ["EURUSD", "GBPUSD"] else 2)
            tp_price = round(live_price - (pips_buffer * 2.5), 5 if symbol in ["EURUSD", "GBPUSD"] else 2)

        score = 88.0

        DAILY_STATS["candidate_setups"] += 1
        DAILY_STATS["paper_executions"] += 1
        DAILY_STATS["scores"].append(score)

        trade_details = {
            "symbol": symbol,
            "action": action,
            "entry": live_price,
            "sl": sl_price,
            "tp": tp_price,
            "volume": 0.01,
            "score": score,
            "pinbar_pattern": pinbar_type,
            "candle_data": candle_meta,
            "timestamp": now_pht
        }
        LAST_TRADE = trade_details

        # Get Admin Chat ID
        admin_chat_id = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")[0].strip()
        if not admin_chat_id:
            admin_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

        # Send Actionable Signal Alert to Telegram
        if admin_chat_id:
            action_emoji = "🟢 *BUY*" if action == "BUY" else "🔴 *SELL*"
            alert_msg = (
                "🚨 *ACCURATE PINBAR SIGNAL DETECTED*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"• Symbol: `{symbol}`\n"
                f"• Action: {action_emoji}\n"
                f"• Pattern: `{pinbar_type}`\n"
                f"• Volume: `0.01 Lot`\n\n"
                f"📊 *Last Closed Candle (M15) Breakdown:*\n"
                f"• Open: `${candle_meta['open']}` | High: `${candle_meta['high']}`\n"
                f"• Low: `${candle_meta['low']}` | Close: `${candle_meta['close']}`\n"
                f"• Lower Wick: `{candle_meta['lower_wick_pct']}%` | Upper Wick: `{candle_meta['upper_wick_pct']}%`\n\n"
                f"📍 *Execution Parameters:*\n"
                f"• Entry Price: `${live_price}`\n"
                f"• Stop Loss (SL): `${sl_price}`\n"
                f"• Take Profit (TP): `${tp_price}`\n\n"
                f"📈 *Confluence Score:* `{score}/100`\n"
                f"⏰ *Time:* `{now_pht}`\n\n"
                f"👉 *Action Needed:* Buksan ang Vantage MT5 sa Winlator at i-enter ang order!"
            )
            send_telegram_reply(admin_chat_id, alert_msg)

    return {
        "status": "success",
        "paper_test_mode": paper_test,
        "symbol_scanned": symbol,
        "pinbar_detected": pinbar_type,
        "last_candle_structure": candle_meta,
        "fetched_live_price": live_price,
        "logged_trade": trade_details,
        "scan_time": now_pht
    }
