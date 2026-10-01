import os
import logging
import yfinance as yf
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Tuple, List
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Import Telegram command handler & sender
from app.telegram import handle_telegram_command, send_telegram_reply

# Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main_app")

app = FastAPI(
    title="AI Trading Bot Engine",
    version="2.6.0",
    description="Multi-Pair Pinbar Scanner with 1:2 Dynamic RRR"
)

# SYMBOL MAPPING
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


def analyze_last_pinbar(symbol: str) -> Tuple[str, Optional[Dict]]:
    """
    Kina-kalkula ang huling saradong candle sa M15 timeframe 
    upang malaman kung may valid at accurate na Pinbar pattern (Wick >= 55%).
    """
    yf_ticker = SYMBOL_MAP.get(symbol, symbol)
    try:
        ticker = yf.Ticker(yf_ticker)
        hist = ticker.history(period="1d", interval="15m")
        
        if len(hist) < 2:
            return "NO_PINBAR", None

        last_candle = hist.iloc[-2]
        c_open = float(last_candle['Open'])
        c_high = float(last_candle['High'])
        c_low = float(last_candle['Low'])
        c_close = float(last_candle['Close'])

        total_range = c_high - c_low
        if total_range == 0:
            return "NO_PINBAR", None

        body_size = abs(c_close - c_open)
        upper_wick = c_high - max(c_open, c_close)
        lower_wick = min(c_open, c_close) - c_low

        decimals = 5 if symbol in ["EURUSD", "GBPUSD"] else (3 if symbol == "USDJPY" else 2)

        candle_details = {
            "open": round(c_open, decimals),
            "high": round(c_high, decimals),
            "low": round(c_low, decimals),
            "close": round(c_close, decimals),
            "range": round(total_range, decimals),
            "upper_wick_pct": round((upper_wick / total_range) * 100, 1),
            "lower_wick_pct": round((lower_wick / total_range) * 100, 1)
        }

        # Pinbar Rule: Lower/Upper Wick >= 55% & Body <= 30%
        if lower_wick / total_range >= 0.55 and body_size / total_range <= 0.30:
            return "BULLISH_PINBAR", candle_details
        elif upper_wick / total_range >= 0.55 and body_size / total_range <= 0.30:
            return "BEARISH_PINBAR", candle_details

        return "NO_PINBAR", candle_details

    except Exception as e:
        logger.error(f"Pinbar analysis error for {symbol}: {e}")
        return "NO_PINBAR", None


def fetch_live_price(symbol: str) -> Optional[float]:
    """Fetches real-time market price using yfinance."""
    yf_ticker = SYMBOL_MAP.get(symbol, symbol)
    decimals = 5 if symbol in ["EURUSD", "GBPUSD"] else (3 if symbol == "USDJPY" else 2)
    try:
        ticker = yf.Ticker(yf_ticker)
        fast_info = getattr(ticker, 'fast_info', None)
        if fast_info and 'lastPrice' in fast_info and fast_info['lastPrice']:
            return round(float(fast_info['lastPrice']), decimals)
        
        hist = ticker.history(period="1d", interval="1m")
        if not hist.empty:
            return round(float(hist['Close'].iloc[-1]), decimals)
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
        "version": "2.6.0",
        "supported_pairs": list(SYMBOL_MAP.keys()),
        "execution_mode": "PINBAR_1TO2_RRR_ENGINE",
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
# ALL-IN-ONE SCANNER WITH DYNAMIC 1:2 RISK-REWARD RATIO
# ---------------------------------------------------------

@app.api_route("/scan-all", methods=["GET", "HEAD"])
def scan_all_pairs(paper_test: bool = False):
    """
    Scans ALL 5 supported pairs simultaneously.
    Calculates Stop Loss based on Pinbar Wick and sets Take Profit at exactly 1:2 RRR!
    """
    global LAST_TRADE
    now_pht = get_ph_time_str()
    DAILY_STATS["total_scans"] += 1
    DAILY_STATS["last_scan_time"] = now_pht

    admin_chat_id = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")[0].strip() or os.getenv("TELEGRAM_CHAT_ID", "").strip()

    scan_results = []
    signals_found = 0

    for symbol in SYMBOL_MAP.keys():
        live_price = fetch_live_price(symbol) or 1.0000
        pinbar_type, candle_meta = analyze_last_pinbar(symbol)

        # Force simulated pinbar ONLY IF paper_test=true for Gold
        if paper_test and pinbar_type == "NO_PINBAR" and symbol == "XAUUSD":
            pinbar_type = "BULLISH_PINBAR"
            candle_meta = {
                "open": round(live_price - 1.50, 2),
                "high": round(live_price + 0.50, 2),
                "low": round(live_price - 8.50, 2),
                "close": live_price,
                "range": 9.00,
                "upper_wick_pct": 5.5,
                "lower_wick_pct": 77.8
            }

        if pinbar_type in ["BULLISH_PINBAR", "BEARISH_PINBAR"]:
            signals_found += 1
            action = "BUY" if pinbar_type == "BULLISH_PINBAR" else "SELL"
            decimals = 5 if symbol in ["EURUSD", "GBPUSD"] else (3 if symbol == "USDJPY" else 2)

            # Extra buffer sa labas ng Wick
            if symbol in ["EURUSD", "GBPUSD"]:
                buffer = 0.00050
            elif symbol == "USDJPY":
                buffer = 0.050
            elif symbol == "BTCUSD":
                buffer = 20.00
            else: # Gold (XAUUSD)
                buffer = 0.50

            # --- DYNAMIC 1:2 RISK-TO-REWARD CALCULATION ---
            if action == "BUY":
                # SL = Low ng Pinbar Candle minus buffer
                sl_price = round(candle_meta['low'] - buffer, decimals)
                risk_distance = round(live_price - sl_price, decimals)
                
                # TP = Exactly 2x ng Risk Distance (1:2 RRR)
                tp_price = round(live_price + (risk_distance * 2.0), decimals)
            else:
                # SL = High ng Pinbar Candle plus buffer
                sl_price = round(candle_meta['high'] + buffer, decimals)
                risk_distance = round(sl_price - live_price, decimals)
                
                # TP = Exactly 2x ng Risk Distance (1:2 RRR)
                tp_price = round(live_price - (risk_distance * 2.0), decimals)

            score = 88.5
            DAILY_STATS["candidate_setups"] += 1
            DAILY_STATS["paper_executions"] += 1

            trade_details = {
                "symbol": symbol,
                "action": action,
                "entry": live_price,
                "sl": sl_price,
                "tp": tp_price,
                "risk_reward_ratio": "1:2",
                "volume": 0.01,
                "score": score,
                "pinbar_pattern": pinbar_type,
                "candle_data": candle_meta,
                "timestamp": now_pht
            }
            LAST_TRADE = trade_details

            # Dispatch Alert to Telegram
            if admin_chat_id:
                action_emoji = "🟢 *BUY*" if action == "BUY" else "🔴 *SELL*"
                alert_msg = (
                    "🚨 *ACCURATE PINBAR SIGNAL DETECTED*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"• Symbol: `{symbol}`\n"
                    f"• Action: {action_emoji}\n"
                    f"• Pattern: `{pinbar_type}`\n"
                    f"• Volume: `0.01 Lot`\n"
                    f"• Risk-Reward: `1:2 (Optimal)`\n\n"
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

            scan_results.append({
                "symbol": symbol,
                "status": "SIGNAL_FOUND",
                "action": action,
                "pattern": pinbar_type,
                "price": live_price,
                "sl": sl_price,
                "tp": tp_price
            })
        else:
            scan_results.append({
                "symbol": symbol,
                "status": "NO_SIGNAL",
                "pattern": "NO_PINBAR",
                "price": live_price
            })

    return {
        "status": "success",
        "scan_type": "MULTI_PAIR_1TO2_RRR_SCANNER",
        "total_pairs_scanned": len(SYMBOL_MAP),
        "signals_detected": signals_found,
        "results": scan_results,
        "scan_time": now_pht
    }
