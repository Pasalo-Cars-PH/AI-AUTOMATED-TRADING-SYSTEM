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
    version="4.0.0",
    description="Full Institutional Smart Money Concepts (SMC) + Pinbar Engine"
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


def check_full_smc_confluence(df, action: str, current_price: float) -> Dict[str, str]:
    """
    FULL SMC ENGINE:
    Calculates BOS, CHoCH, Premium/Discount Zones, Order Blocks, FVG, and Liquidity Sweeps.
    """
    if len(df) < 20:
        return {
            "structure": "NEUTRAL",
            "zone": "EQUILIBRIUM",
            "order_block": "NO",
            "fvg": "NO",
            "liquidity_sweep": "NO"
        }

    recent_20 = df.iloc[-20:-2]
    current_candle = df.iloc[-2]

    range_high = recent_20['High'].max()
    range_low = recent_20['Low'].min()
    equilibrium = (range_high + range_low) / 2.0

    # 1. Premium / Discount Zone Check
    if action == "BUY":
        zone = "DISCOUNT (CHEAP)" if current_price < equilibrium else "PREMIUM (EXPENSIVE)"
    else:
        zone = "PREMIUM (EXPENSIVE)" if current_price > equilibrium else "DISCOUNT (CHEAP)"

    # 2. BOS / CHoCH Structure Check
    prev_high = recent_20.iloc[-10:-3]['High'].max()
    prev_low = recent_20.iloc[-10:-3]['Low'].min()

    if action == "BUY":
        if current_candle['Close'] > prev_high:
            structure = "CHoCH (BULLISH REVERSAL)"
        elif current_candle['High'] > prev_high:
            structure = "BOS (BULLISH CONTINUATION)"
        else:
            structure = "RANGE_ALIGNED"
    else:
        if current_candle['Close'] < prev_low:
            structure = "CHoCH (BEARISH REVERSAL)"
        elif current_candle['Low'] < prev_low:
            structure = "BOS (BEARISH CONTINUATION)"
        else:
            structure = "RANGE_ALIGNED"

    # 3. Order Block Detection
    ob_status = "NO"
    if action == "BUY" and current_candle['Low'] <= range_low * 1.001:
        ob_status = "DEMAND_OB"
    elif action == "SELL" and current_candle['High'] >= range_high * 0.999:
        ob_status = "SUPPLY_OB"

    # 4. Fair Value Gap (FVG)
    fvg_status = "NO"
    for i in range(len(df) - 6, len(df) - 2):
        c1 = df.iloc[i-1]
        c3 = df.iloc[i+1]
        if action == "BUY" and c3['Low'] > c1['High']:
            fvg_status = "BULLISH_FVG"
            break
        elif action == "SELL" and c3['High'] < c1['Low']:
            fvg_status = "BEARISH_FVG"
            break

    # 5. Liquidity Sweep Detection
    sweep_status = "NO"
    if action == "BUY" and current_candle['Low'] < prev_low:
        sweep_status = "SSL_SWEPT (SELL-SIDE)"
    elif action == "SELL" and current_candle['High'] > prev_high:
        sweep_status = "BSL_SWEPT (BUY-SIDE)"

    return {
        "structure": structure,
        "zone": zone,
        "order_block": ob_status,
        "fvg": fvg_status,
        "liquidity_sweep": sweep_status
    }


def analyze_last_pinbar(symbol: str) -> Tuple[str, Optional[Dict], Dict[str, str]]:
    """
    Kina-kalkula ang M15 Pinbar pattern at tina-tsek ang Full SMC Confluences.
    """
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
        hist = ticker.history(period="3d", interval="15m")
        
        if len(hist) < 20:
            return "NO_PINBAR", None, smc_analysis

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

        # Pinbar Rule: Lower/Upper Wick >= 55% & Body <= 30%
        if lower_wick / total_range >= 0.55 and body_size / total_range <= 0.30:
            smc_analysis = check_full_smc_confluence(hist, "BUY", c_close)
            return "BULLISH_PINBAR", candle_details, smc_analysis
        elif upper_wick / total_range >= 0.55 and body_size / total_range <= 0.30:
            smc_analysis = check_full_smc_confluence(hist, "SELL", c_close)
            return "BEARISH_PINBAR", candle_details, smc_analysis

        return "NO_PINBAR", candle_details, smc_analysis

    except Exception as e:
        logger.error(f"Pinbar analysis error for {symbol}: {e}")
        return "NO_PINBAR", None, smc_analysis


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
        "version": "4.0.0",
        "supported_pairs": list(SYMBOL_MAP.keys()),
        "execution_mode": "FULL_SMC_INSTITUTIONAL_ENGINE",
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
# ALL-IN-ONE SCANNER WITH FULL SMC ENGINE & 1:2 RRR
# ---------------------------------------------------------

@app.api_route("/scan-all", methods=["GET", "HEAD"])
def scan_all_pairs(paper_test: bool = False):
    global LAST_TRADE
    now_pht = get_ph_time_str()
    DAILY_STATS["total_scans"] += 1
    DAILY_STATS["last_scan_time"] = now_pht

    admin_chat_id = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")[0].strip() or os.getenv("TELEGRAM_CHAT_ID", "").strip()

    scan_results = []
    signals_found = 0

    for symbol in SYMBOL_MAP.keys():
        live_price = fetch_live_price(symbol) or 1.0000
        pinbar_type, candle_meta, smc_analysis = analyze_last_pinbar(symbol)

        # Paper test simulation override
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
            smc_analysis = {
                "structure": "CHoCH (BULLISH REVERSAL)",
                "zone": "DISCOUNT (CHEAP)",
                "order_block": "DEMAND_OB",
                "fvg": "BULLISH_FVG",
                "liquidity_sweep": "SSL_SWEPT (SELL-SIDE)"
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

            # Dynamic 1:2 Risk-to-Reward Calculation
            if action == "BUY":
                sl_price = round(candle_meta['low'] - buffer, decimals)
                risk_distance = round(live_price - sl_price, decimals)
                tp_price = round(live_price + (risk_distance * 2.0), decimals)
            else:
                sl_price = round(candle_meta['high'] + buffer, decimals)
                risk_distance = round(sl_price - live_price, decimals)
                tp_price = round(live_price - (risk_distance * 2.0), decimals)

            # Institutional Confluence Scoring
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

            # Dispatch Alert to Telegram
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
                    f"👉 *Action Needed:* Buksan ang Vantage MT5 sa Winlator at i-enter ang order!"
                )
                send_telegram_reply(admin_chat_id, alert_msg)

            scan_results.append({
                "symbol": symbol,
                "status": "SIGNAL_FOUND",
                "action": action,
                "smc": smc_analysis,
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
        "scan_type": "MULTI_PAIR_FULL_SMC_SCANNER",
        "signals_detected": signals_found,
        "results": scan_results,
        "scan_time": now_pht
    }

