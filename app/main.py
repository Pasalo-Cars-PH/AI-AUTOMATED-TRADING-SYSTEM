import os
import logging
import requests
import yfinance as yf
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Tuple
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.telegram import handle_telegram_command, send_telegram_reply

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main_app")

app = FastAPI(
    title="AI Trading Bot Engine",
    version="4.3.0",
    description="Fixed Risk Math (SL/TP) & Strict M15 SMC Pattern Engine"
)

SYMBOL_MAP = {
    "XAUUSD": "GC=F",      
    "EURUSD": "EURUSD=X",  
    "GBPUSD": "GBPUSD=X",  
    "USDJPY": "JPY=X",      
    "BTCUSD": "BTC-USD"    
}

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
    ph_tz = timezone(timedelta(hours=8))
    return datetime.now(ph_tz).strftime("%Y-%m-%d %I:%M:%S %p PHT")


def fetch_live_price(symbol: str) -> Optional[float]:
    """Fetches real-time price using direct Gold Spot API or yfinance."""
    decimals = 5 if symbol in ["EURUSD", "GBPUSD"] else (3 if symbol == "USDJPY" else 2)

    # Primary: Direct Exchange Rate API for Spot Gold
    try:
        if symbol == "XAUUSD":
            res = requests.get("https://open.er-api.com/v6/latest/XAU", timeout=4)
            if res.status_code == 200:
                rates = res.json().get("rates", {})
                usd_price = rates.get("USD")
                if usd_price and usd_price > 0:
                    return round(1.0 / float(usd_price), decimals)
    except Exception as e:
        logger.warning(f"Spot API failed for {symbol}: {e}")

    # Fallback: Yahoo Finance
    yf_ticker = SYMBOL_MAP.get(symbol, symbol)
    try:
        ticker = yf.Ticker(yf_ticker)
        hist = ticker.history(period="1d", interval="1m")
        if not hist.empty:
            price = float(hist['Close'].iloc[-1])
            return round(price, decimals)
    except Exception as e:
        logger.error(f"yfinance fetch failed for {symbol}: {e}")

    return None


def check_full_smc_confluence(df, action: str, current_price: float) -> Dict[str, str]:
    if len(df) < 20:
        return {
            "structure": "NEUTRAL",
            "zone": "EQUILIBRIUM",
            "order_block": "NO",
            "fvg": "NO",
            "liquidity_sweep": "NO"
        }

    recent_20 = df.iloc[-20:-1]
    last_completed = df.iloc[-2]

    range_high = recent_20['High'].max()
    range_low = recent_20['Low'].min()
    equilibrium = (range_high + range_low) / 2.0

    zone = "DISCOUNT (CHEAP)" if current_price < equilibrium else "PREMIUM (EXPENSIVE)"

    prev_high = recent_20.iloc[-10:-3]['High'].max()
    prev_low = recent_20.iloc[-10:-3]['Low'].min()

    if action == "BUY":
        if last_completed['Close'] > prev_high:
            structure = "CHoCH (BULLISH REVERSAL)"
        elif last_completed['High'] > prev_high:
            structure = "BOS (BULLISH CONTINUATION)"
        else:
            structure = "RANGE_ALIGNED"
    else:
        if last_completed['Close'] < prev_low:
            structure = "CHoCH (BEARISH REVERSAL)"
        elif last_completed['Low'] < prev_low:
            structure = "BOS (BEARISH CONTINUATION)"
        else:
            structure = "RANGE_ALIGNED"

    ob_status = "NO"
    if action == "BUY" and last_completed['Low'] <= range_low * 1.001:
        ob_status = "DEMAND_OB"
    elif action == "SELL" and last_completed['High'] >= range_high * 0.999:
        ob_status = "SUPPLY_OB"

    fvg_status = "NO"
    if len(df) >= 5:
        c1 = df.iloc[-4]
        c3 = df.iloc[-2]
        if action == "BUY" and c3['Low'] > c1['High']:
            fvg_status = "BULLISH_FVG"
        elif action == "SELL" and c3['High'] < c1['Low']:
            fvg_status = "BEARISH_FVG"

    sweep_status = "NO"
    if action == "BUY" and last_completed['Low'] < prev_low and last_completed['Close'] > prev_low:
        sweep_status = "SSL_SWEPT (SELL-SIDE)"
    elif action == "SELL" and last_completed['High'] > prev_high and last_completed['Close'] < prev_high:
        sweep_status = "BSL_SWEPT (BUY-SIDE)"

    return {
        "structure": structure,
        "zone": zone,
        "order_block": ob_status,
        "fvg": fvg_status,
        "liquidity_sweep": sweep_status
    }


def analyze_last_pinbar(symbol: str, live_spot_price: float) -> Tuple[str, Optional[Dict], Dict[str, str]]:
    yf_ticker = SYMBOL_MAP.get(symbol, symbol)
    smc_analysis = {
        "structure": "NEUTRAL",
        "zone": "EQUILIBRIUM",
        "order_block": "NO",
        "fvg": "NO",
        "liquidity_sweep": "NO"
    }

    try:
        ticker = yf.Ticker(yf_ticker)
        hist = ticker.history(period="5d", interval="15m")
        
        if len(hist) < 20:
            return "NO_PINBAR", None, smc_analysis

        # Analyze last completed bar
        last_candle = hist.iloc[-2]
        c_open = float(last_candle['Open'])
        c_high = float(last_candle['High'])
        c_low = float(last_candle['Low'])
        c_close = float(last_candle['Close'])

        total_range = c_high - c_low
        if total_range == 0:
            return "NO_PINBAR", None, smc_analysis

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

        # Strict Pinbar Logic: Wick must be >= 60% of candle range, Body <= 25%
        if lower_wick / total_range >= 0.60 and body_size / total_range <= 0.25:
            smc_analysis = check_full_smc_confluence(hist, "BUY", live_spot_price)
            return "BULLISH_PINBAR", candle_details, smc_analysis
        elif upper_wick / total_range >= 0.60 and body_size / total_range <= 0.25:
            smc_analysis = check_full_smc_confluence(hist, "SELL", live_spot_price)
            return "BEARISH_PINBAR", candle_details, smc_analysis

        return "NO_PINBAR", candle_details, smc_analysis

    except Exception as e:
        logger.error(f"Pinbar analysis error for {symbol}: {e}")
        return "NO_PINBAR", None, smc_analysis


@app.api_route("/", methods=["GET", "HEAD"])
def root_status():
    return {
        "status": "online",
        "service": "AI Trading Bot Engine",
        "version": "4.3.0",
        "supported_pairs": list(SYMBOL_MAP.keys()),
        "server_ph_time": get_ph_time_str()
    }


@app.api_route("/health", methods=["GET", "HEAD"])
def health_check():
    return {"status": "ok", "telegram_observability": "active"}


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


@app.api_route("/scan-all", methods=["GET", "HEAD"])
def scan_all_pairs():
    global LAST_TRADE
    now_pht = get_ph_time_str()
    DAILY_STATS["total_scans"] += 1
    DAILY_STATS["last_scan_time"] = now_pht

    admin_chat_id = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")[0].strip() or os.getenv("TELEGRAM_CHAT_ID", "").strip()

    scan_results = []
    signals_found = 0

    for symbol in SYMBOL_MAP.keys():
        live_price = fetch_live_price(symbol)
        if not live_price:
            continue

        pinbar_type, candle_meta, smc_analysis = analyze_last_pinbar(symbol, live_price)

        if pinbar_type in ["BULLISH_PINBAR", "BEARISH_PINBAR"]:
            action = "BUY" if pinbar_type == "BULLISH_PINBAR" else "SELL"
            
            # Reject signal if there's no Liquidity Sweep or Order Block
            if smc_analysis["liquidity_sweep"] == "NO" and smc_analysis["order_block"] == "NO":
                DAILY_STATS["rejected_candidates"] += 1
                continue

            decimals = 5 if symbol in ["EURUSD", "GBPUSD"] else (3 if symbol == "USDJPY" else 2)
            
            # Dynamic buffer allocation
            if symbol == "XAUUSD":
                buffer = 0.50
            elif symbol == "BTCUSD":
                buffer = 50.00
            else:
                buffer = 0.00050

            # CORRECTED RISK MATH FOR BUY & SELL TRADES
            if action == "BUY":
                sl_price = round(candle_meta['low'] - buffer, decimals)
                risk_distance = abs(live_price - sl_price)
                tp_price = round(live_price + (risk_distance * 2.0), decimals)
            else: # SELL ACTION
                sl_price = round(candle_meta['high'] + buffer, decimals)
                risk_distance = abs(sl_price - live_price)
                tp_price = round(live_price - (risk_distance * 2.0), decimals)

            signals_found += 1

            score = 60.0
            if "DISCOUNT" in smc_analysis["zone"] and action == "BUY": score += 10.0
            if "PREMIUM" in smc_analysis["zone"] and action == "SELL": score += 10.0
            if smc_analysis["order_block"] != "NO": score += 10.0
            if smc_analysis["fvg"] != "NO": score += 10.0
            if smc_analysis["liquidity_sweep"] != "NO": score += 10.0
            score = min(score, 100.0)

            DAILY_STATS["candidate_setups"] += 1
            DAILY_STATS["paper_executions"] += 1

            trade_details = {
                "symbol": symbol,
                "action": action,
                "entry": live_price,
                "sl": sl_price,
                "tp": tp_price,
                "risk_reward_ratio": "1:2",
                "smc_details": smc_analysis,
                "score": score,
                "timestamp": now_pht
            }
            LAST_TRADE = trade_details

            if admin_chat_id:
                action_emoji = "🟢 *BUY*" if action == "BUY" else "🔴 *SELL*"
                alert_msg = (
                    "🚨 *FULL INSTITUTIONAL SMC SIGNAL DETECTED*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"• Symbol: `{symbol}`\n"
                    f"• Action: {action_emoji}\n"
                    f"• Pattern: `{pinbar_type}`\n"
                    f"• Risk-Reward: `1:2 (Optimal)`\n\n"
                    f"🏛️ *Smart Money Concepts (SMC):*\n"
                    f"• Structure: `{smc_analysis['structure']}`\n"
                    f"• Market Zone: `{smc_analysis['zone']}`\n"
                    f"• Order Block: `{smc_analysis['order_block']}`\n"
                    f"• Fair Value Gap: `{smc_analysis['fvg']}`\n"
                    f"• Liquidity Sweep: `{smc_analysis['liquidity_sweep']}`\n\n"
                    f"📍 *Execution Parameters:*\n"
                    f"• Entry Price: `${live_price}`\n"
                    f"• Stop Loss (SL): `${sl_price}`\n"
                    f"• Take Profit (TP): `${tp_price}`\n\n"
                    f"📈 *Institutional Confluence Score:* `{score}/100`\n"
                    f"⏰ *Time:* `{now_pht}`\n\n"
                    f"👉 *Action Needed:* Buksan ang Vantage MT5 at i-enter ang order!"
                )
                send_telegram_reply(admin_chat_id, alert_msg)

            scan_results.append({
                "symbol": symbol,
                "status": "SIGNAL_FOUND",
                "action": action,
                "price": live_price,
                "sl": sl_price,
                "tp": tp_price
            })
        else:
            scan_results.append({"symbol": symbol, "status": "NO_SIGNAL", "price": live_price})

    return {
        "status": "success",
        "scan_type": "STRICT_SMC_M15_SPOT_SCAN",
        "signals_detected": signals_found,
        "results": scan_results,
        "scan_time": now_pht
    }
