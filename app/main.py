import os
import uuid
import time
import logging
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Tuple, Any, List
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from apscheduler.schedulers.background import BackgroundScheduler

from app.telegram import handle_telegram_command, send_telegram_reply

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("smc_engine_v5_3")

app = FastAPI(
    title="Institutional SMC V5.3 Canonical Spot Engine",
    version="5.3.0",
    description="Multi-Timeframe SMC Engine (H1 Structure -> M15 Setup -> M5 Trigger) utilizing Twelve Data Canonical Spot Feeds"
)

# TOP 3 HIGH VOLATILITY CANONICAL SPOT PAIR MAP
SYMBOL_MAP = {
    "XAUUSD": {"canonical": "XAU/USD", "yahoo_fallback": "GC=F"},
    "GBPUSD": {"canonical": "GBP/USD", "yahoo_fallback": "GBPUSD=X"},
    "EURUSD": {"canonical": "EUR/USD", "yahoo_fallback": "EURUSD=X"}
}

# FLEXIBLE API KEY READER
TWELVE_DATA_API_KEY = (
    os.getenv("TWELVE_DATA_API_KEY") or 
    os.getenv("TWELVEDATA_API_KEY") or 
    ""
).strip()

SYSTEM_STATE = {
    "mode": "PAPER_VALIDATION",
    "paper_session_enabled": True,       # Auto-enabled for scheduler
    "master_live_enable": False,        
    "kill_switch": False,                
    "strict_canonical_only": False,     
    "news_mode": "FALLBACK_WATCH",      
    "execution_lock": "STRICT_PAPER_ONLY",
    "data_provider": "TWELVE_DATA_SPOT"
}

DAILY_STATS = {
    "total_scans": 0,
    "candidate_setups": 0,
    "paper_executions": 0,
    "rejected_candidates": 0,
    "last_scan_time": "N/A"
}

PAPER_JOURNAL: Dict[str, Dict[str, Any]] = {}
LAST_TRADE = None


def get_ph_now() -> datetime:
    ph_tz = timezone(timedelta(hours=8))
    return datetime.now(ph_tz)


def get_ph_time_str() -> str:
    return get_ph_now().strftime("%Y-%m-%d %I:%M:%S %p PHT")


# ------------------------------------------------------------------
# CANONICAL SPOT DATA FETCHING WITH RATE LIMIT PROTECTION
# ------------------------------------------------------------------
def fetch_twelve_data_time_series(symbol: str, interval: str, outputsize: int = 30) -> Optional[pd.DataFrame]:
    """Fetches real-time spot time-series candles with safe delay."""
    if not TWELVE_DATA_API_KEY:
        return None
        
    canonical_symbol = SYMBOL_MAP.get(symbol, {}).get("canonical", symbol)
    url = f"https://api.twelvedata.com/time_series?symbol={canonical_symbol}&interval={interval}&outputsize={outputsize}&apikey={TWELVE_DATA_API_KEY}"
    
    try:
        time.sleep(1.5) 
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if "values" not in data:
            logger.warning(f"Twelve Data limit/error for {symbol}: {data.get('message', 'No values')}")
            return None
            
        df = pd.DataFrame(data["values"])
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.sort_values('datetime').reset_index(drop=True)
        
        for col in ['open', 'high', 'low', 'close']:
            df[col] = df[col].astype(float)
            
        df.rename(columns={
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'datetime': 'Datetime'
        }, inplace=True)
        
        df.set_index('Datetime', inplace=True)
        return df
    except Exception as e:
        logger.error(f"Twelve Data HTTP Request error for {symbol}: {e}")
        return None


def fetch_symbol_data(symbol: str) -> Tuple[Dict[str, pd.DataFrame], str]:
    """Retrieves multi-timeframe candle data for H1, M15, and M5."""
    h1_df = fetch_twelve_data_time_series(symbol, "1h", 30)
    m15_df = fetch_twelve_data_time_series(symbol, "15min", 30)
    m5_df = fetch_twelve_data_time_series(symbol, "5min", 30)
    
    if h1_df is not None and m15_df is not None and m5_df is not None:
        if not h1_df.empty and not m15_df.empty and not m5_df.empty:
            return {"h1": h1_df, "m15": m15_df, "m5": m5_df}, "TWELVE_DATA_SPOT"

    if not SYSTEM_STATE["strict_canonical_only"]:
        logger.warning(f"Twelve Data feed unavailable for {symbol}. Falling back to Yahoo Proxy.")
        yahoo_symbol = SYMBOL_MAP.get(symbol, {}).get("yahoo_fallback", symbol)
        ticker = yf.Ticker(yahoo_symbol)
        
        try:
            h1_fallback = ticker.history(period="10d", interval="60m")
            m15_fallback = ticker.history(period="5d", interval="15m")
            m5_fallback = ticker.history(period="2d", interval="5m")
            
            if not h1_fallback.empty and not m15_fallback.empty and not m5_fallback.empty:
                return {"h1": h1_fallback, "m15": m15_fallback, "m5": m5_fallback}, "EMERGENCY_YAHOO_FALLBACK"
        except Exception as e:
            logger.error(f"Yahoo Fallback error for {symbol}: {e}")
            
    return {}, "UNAVAILABLE"


# ------------------------------------------------------------------
# SMC LOGIC ENGINE
# ------------------------------------------------------------------
def analyze_h1_structure(df_h1: pd.DataFrame) -> Dict[str, Any]:
    if len(df_h1) < 20:
        return {"bias": "NEUTRAL", "bos": False, "high": 0, "low": 0}
    
    recent_20 = df_h1.iloc[-20:-1]
    swing_high = float(recent_20['High'].max())
    swing_low = float(recent_20['Low'].min())
    last_closed = df_h1.iloc[-2]
    
    bos = False
    bias = "NEUTRAL"
    
    if float(last_closed['Close']) > swing_high:
        bos = True
        bias = "BULLISH"
    elif float(last_closed['Close']) < swing_low:
        bos = True
        bias = "BEARISH"
    else:
        recent_10 = df_h1.iloc[-10:-1]
        if recent_10['High'].iloc[-1] > recent_10['High'].iloc[-5] and recent_10['Low'].iloc[-1] > recent_10['Low'].iloc[-5]:
            bias = "BULLISH"
        elif recent_10['High'].iloc[-1] < recent_10['High'].iloc[-5] and recent_10['Low'].iloc[-1] < recent_10['Low'].iloc[-5]:
            bias = "BEARISH"
            
    return {"bias": bias, "bos": bos, "swing_high": swing_high, "swing_low": swing_low}


def analyze_m15_setup(df_m15: pd.DataFrame, h1_bias: str) -> Dict[str, Any]:
    if len(df_m15) < 20 or h1_bias == "NEUTRAL":
        return {"setup_valid": False}
    
    recent_20 = df_m15.iloc[-20:-1]
    last_candle = df_m15.iloc[-2]
    live_price = float(df_m15.iloc[-1]['Close'])
    
    range_high = float(recent_20['High'].max())
    range_low = float(recent_20['Low'].min())
    equilibrium = (range_high + range_low) / 2.0
    
    market_zone = "DISCOUNT" if live_price < equilibrium else "PREMIUM"
    
    prev_high = float(recent_20.iloc[-12:-4]['High'].max())
    prev_low = float(recent_20.iloc[-12:-4]['Low'].min())
    
    action = None
    sweep = False
    ob_present = False
    fvg_present = False
    bos_m15 = False
    
    if h1_bias == "BULLISH" and market_zone == "DISCOUNT":
        action = "BUY"
        if last_candle['Low'] < prev_low and last_candle['Close'] > prev_low:
            sweep = True
        if last_candle['Low'] <= range_low * 1.0005:
            ob_present = True
        if len(df_m15) >= 5 and df_m15.iloc[-2]['Low'] > df_m15.iloc[-4]['High']:
            fvg_present = True
        if last_candle['Close'] > prev_high:
            bos_m15 = True
            
    elif h1_bias == "BEARISH" and market_zone == "PREMIUM":
        action = "SELL"
        if last_candle['High'] > prev_high and last_candle['Close'] < prev_high:
            sweep = True
        if last_candle['High'] >= range_high * 0.9995:
            ob_present = True
        if len(df_m15) >= 5 and df_m15.iloc[-2]['High'] < df_m15.iloc[-4]['Low']:
            fvg_present = True
        if last_candle['Close'] < prev_low:
            bos_m15 = True
            
    setup_valid = action is not None and (sweep or ob_present or bos_m15)
    
    return {
        "setup_valid": setup_valid,
        "action": action,
        "zone": market_zone,
        "sweep": sweep,
        "order_block": ob_present,
        "fvg": fvg_present,
        "bos": bos_m15,
        "live_price": live_price,
        "low_bound": range_low,
        "high_bound": range_high
    }


def analyze_m5_trigger(df_m5: pd.DataFrame, action: str) -> Tuple[bool, Dict[str, bool]]:
    if len(df_m5) < 10:
        return False, {"displacement": False, "reclaim": False, "closed_conf": False}
    
    recent_10 = df_m5.iloc[-10:-2]
    last_closed = df_m5.iloc[-2]
    
    c_open = float(last_closed['Open'])
    c_high = float(last_closed['High'])
    c_low = float(last_closed['Low'])
    c_close = float(last_closed['Close'])
    
    candle_range = c_high - c_low
    body_size = abs(c_close - c_open)
    
    closed_conf = (c_close > c_open) if action == "BUY" else (c_close < c_open)
    displacement = (body_size / candle_range >= 0.50) if candle_range > 0 else False
    
    reclaim = False
    if action == "BUY":
        prev_m5_low = float(recent_10['Low'].min())
        reclaim = (last_closed['Low'] <= prev_m5_low) and (c_close > prev_m5_low)
    else:
        prev_m5_high = float(recent_10['High'].max())
        reclaim = (last_closed['High'] >= prev_m5_high) and (c_close < prev_m5_high)
        
    m5_passed = closed_conf and (displacement or reclaim)
    return m5_passed, {"displacement": displacement, "reclaim": reclaim, "closed_conf": closed_conf}


def evaluate_hard_gates(symbol: str, df_m5: pd.DataFrame, live_price: float, sl: float, tp: float, provider: str) -> Tuple[bool, Dict[str, str]]:
    gate_status = {}
    gate_status["canonical_data_gate"] = "PASS" if not SYSTEM_STATE["strict_canonical_only"] or provider == "TWELVE_DATA_SPOT" else "FAIL"
    
    try:
        latest_candle_time = df_m5.index[-1]
        if isinstance(latest_candle_time, pd.Timestamp):
            latest_candle_time = latest_candle_time.to_pydatetime()
        if latest_candle_time.tzinfo is None:
            latest_candle_time = latest_candle_time.replace(tzinfo=timezone.utc)
            
        now_utc = datetime.now(timezone.utc)
        delta_minutes = (now_utc - latest_candle_time).total_seconds() / 60.0
        gate_status["data_freshness"] = "PASS" if delta_minutes <= 25.0 else f"FAIL_STALE_{int(delta_minutes)}M"
    except Exception:
        gate_status["data_freshness"] = "FAIL_TIMESTAMP"
        
    gate_status["news_gate"] = "PASS_FALLBACK_WATCH"
    risk = abs(live_price - sl)
    reward = abs(tp - live_price)
    rr_ratio = (reward / risk) if risk > 0 else 0
    
    gate_status["risk_gate"] = "PASS" if risk > 0 else "FAIL_ZERO_RISK"
    gate_status["rr_gate"] = "PASS" if rr_ratio >= 1.8 else "FAIL_LOW_RR"
    
    all_passed = all("PASS" in v for v in gate_status.values())
    return all_passed, gate_status


def calculate_confluence_score(h1_ctx: Dict, m15_setup: Dict, m5_details: Dict, rr_passed: bool) -> float:
    score = 0.0
    if h1_ctx["bias"] != "NEUTRAL": score += 15.0
    if m15_setup["bos"]: score += 15.0
    if m15_setup["sweep"]: score += 10.0
    if m15_setup["order_block"]: score += 10.0
    if m15_setup["fvg"]: score += 8.0
    if m15_setup["zone"] in ["DISCOUNT", "PREMIUM"]: score += 7.0
    if m5_details["displacement"]: score += 10.0
    if m5_details["reclaim"]: score += 10.0
    if m5_details["closed_conf"]: score += 10.0
    if rr_passed: score += 5.0
    return min(score, 100.0)


def authorize_paper_execution(system_state: Dict, hard_gates_passed: bool, score: float, m5_passed: bool) -> Tuple[bool, str]:
    if system_state["mode"] != "PAPER_VALIDATION":
        return False, "REJECTED_INVALID_MODE"
    if not system_state["paper_session_enabled"]:
        return False, "REJECTED_PAPER_SESSION_DISABLED"
    if system_state["kill_switch"]:
        return False, "REJECTED_KILL_SWITCH_ACTIVE"
    if not hard_gates_passed:
        return False, "REJECTED_HARD_GATES_FAILED"
    if not m5_passed:
        return False, "REJECTED_M5_TRIGGER_FAILED"
    if score < 75.0:
        return False, "REJECTED_LOW_SCORE"
    return True, "AUTHORIZED"


# ------------------------------------------------------------------
# MAIN SCANNER PIPELINE
# ------------------------------------------------------------------
@app.api_route("/scan-all", methods=["GET", "HEAD"])
def run_smc_v1_pipeline():
    global LAST_TRADE
    now_pht = get_ph_time_str()
    DAILY_STATS["total_scans"] += 1
    DAILY_STATS["last_scan_time"] = now_pht

    admin_chat_id = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")[0].strip() or os.getenv("TELEGRAM_CHAT_ID", "").strip()
    scan_results = []
    accepted_signals_count = 0
    
    for symbol in SYMBOL_MAP.keys():
        data, active_provider = fetch_symbol_data(symbol)
        if not data:
            scan_results.append({"symbol": symbol, "status": "DATA_UNAVAILABLE"})
            continue
            
        h1_ctx = analyze_h1_structure(data["h1"])
        if h1_ctx["bias"] == "NEUTRAL":
            continue
            
        m15_setup = analyze_m15_setup(data["m15"], h1_ctx["bias"])
        if not m15_setup["setup_valid"]:
            scan_results.append({"symbol": symbol, "status": "NO_M15_SETUP"})
            continue
            
        DAILY_STATS["candidate_setups"] += 1
        action = m15_setup["action"]
        live_price = m15_setup["live_price"]
        
        m5_passed, m5_details = analyze_m5_trigger(data["m5"], action)
        
        decimals = 5 if symbol in ["GBPUSD", "EURUSD"] else 2
        buffer = 0.50 if symbol == "XAUUSD" else 0.00050
        
        if action == "BUY":
            sl = round(m15_setup["low_bound"] - buffer, decimals)
            risk = abs(live_price - sl)
            tp = round(live_price + (risk * 2.0), decimals)
        else:
            sl = round(m15_setup["high_bound"] + buffer, decimals)
            risk = abs(sl - live_price)
            tp = round(live_price - (risk * 2.0), decimals)
            
        gates_passed, gate_details = evaluate_hard_gates(symbol, data["m5"], live_price, sl, tp, active_provider)
        score = calculate_confluence_score(h1_ctx, m15_setup, m5_details, gate_details.get("rr_gate") == "PASS")
        is_authorized, auth_reason = authorize_paper_execution(SYSTEM_STATE, gates_passed, score, m5_passed)
        
        if is_authorized:
            DAILY_STATS["paper_executions"] += 1
            accepted_signals_count += 1
            paper_trade_id = f"PT-{uuid.uuid4().hex[:8].upper()}"
            
            trade_payload = {
                "paper_trade_id": paper_trade_id,
                "symbol": symbol,
                "canonical_symbol": SYMBOL_MAP[symbol]["canonical"],
                "direction": action,
                "entry_price": live_price,
                "sl": sl,
                "tp": tp,
                "score": score,
                "entry_timestamp": now_pht,
                "gate_snapshot": gate_details,
                "h1_state": h1_ctx,
                "m15_state": m15_setup,
                "m5_state": m5_details,
                "strategy_version": "5.3.0",
                "data_provider": active_provider,
                "status": "OPEN"
            }
            
            PAPER_JOURNAL[paper_trade_id] = trade_payload
            LAST_TRADE = trade_payload
            
            if admin_chat_id:
                msg = (
                    "🚨 *AUTOMATED SMC TRADE SIGNAL DETECTED*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"• Trade ID: `{paper_trade_id}`\n"
                    f"• Symbol: `{symbol}` ({SYMBOL_MAP[symbol]['canonical']})\n"
                    f"• Direction: `{'BUY' if action == 'BUY' else 'SELL'}`\n"
                    f"• Confluence Score: `{score}/100`\n\n"
                    f"🏛️ *SMC Multi-Timeframe Analysis:*\n"
                    f"• H1 Bias: `{h1_ctx['bias']}` (BOS={h1_ctx['bos']})\n"
                    f"• M15 Setup: `Sweep={m15_setup['sweep']} | OB={m15_setup['order_block']} | BOS={m15_setup['bos']}`\n"
                    f"• M5 Trigger: `Displacement={m5_details['displacement']} | Reclaim={m5_details['reclaim']}`\n\n"
                    f"📍 *Execution Parameters:*\n"
                    f"• Entry Price: `${live_price}`\n"
                    f"• Stop Loss (SL): `${sl}`\n"
                    f"• Take Profit (TP): `${tp}`\n"
                    f"• Target R:R: `1:2.0`\n\n"
                    f"📌 *Provider:* `{active_provider}`"
                )
                send_telegram_reply(admin_chat_id, msg)
                
            scan_results.append({"symbol": symbol, "status": "PAPER_ORDER_ACCEPTED", "trade_id": paper_trade_id, "score": score})
        else:
            DAILY_STATS["rejected_candidates"] += 1
            scan_results.append({"symbol": symbol, "status": auth_reason, "score": score})

    return {
        "status": "success",
        "engine_version": "5.3.0",
        "system_state": SYSTEM_STATE,
        "accepted_signals": accepted_signals_count,
        "results": scan_results,
        "scan_time": now_pht
    }


# ------------------------------------------------------------------
# AUTOMATED SCHEDULER INITIALIZATION (EVERY 5 MINUTES)
# ------------------------------------------------------------------
scheduler = BackgroundScheduler(daemon=True)

def scheduled_market_scan():
    """Runs automatically every 5 minutes."""
    if SYSTEM_STATE["paper_session_enabled"] and not SYSTEM_STATE["kill_switch"]:
        logger.info("⏰ Executing scheduled automated market scan...")
        run_smc_v1_pipeline()

@app.on_event("startup")
def start_automated_scheduler():
    scheduler.add_job(scheduled_market_scan, 'interval', minutes=5)
    scheduler.start()
    logger.info("🚀 Automated 5-minute SMC scheduler started successfully!")

@app.on_event("shutdown")
def stop_automated_scheduler():
    scheduler.shutdown()


@app.api_route("/journal", methods=["GET"])
def get_paper_journal():
    return {"total_paper_orders": len(PAPER_JOURNAL), "journal": list(PAPER_JOURNAL.values())}


@app.api_route("/", methods=["GET", "HEAD"])
def root_status():
    return {"status": "online", "service": "Institutional SMC V5.3 Engine", "version": "5.3.0", "system_state": SYSTEM_STATE}


@app.api_route("/health", methods=["GET", "HEAD"])
def health_check():
    return {"status": "ok", "system_state": SYSTEM_STATE}


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        result = handle_telegram_command(data=data, system_state=SYSTEM_STATE, daily_stats=DAILY_STATS, last_trade=LAST_TRADE)
        return JSONResponse(content=result, status_code=200)
    except Exception as e:
        logger.error(f"Error handling webhook: {e}")
        return JSONResponse(content={"status": "error", "message": str(e)}, status_code=500)
