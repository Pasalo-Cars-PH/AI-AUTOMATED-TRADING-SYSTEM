import os
import datetime
from fastapi import FastAPI, Request
from apscheduler.schedulers.background import BackgroundScheduler
import requests

app = FastAPI(title="SMC Hybrid Scalper Engine")

# Environment Variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")

PAIRS = ["XAUUSD", "GBPUSD", "EURUSD"]
SCANS_TODAY = 0

def send_telegram_msg(message: str, target_chat_id: str = None):
    chat_id = target_chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        print("Telegram tokens missing.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Error sending Telegram alert: {e}")

def fetch_m5_data(symbol: str):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=5min&outputsize=20&apikey={TWELVE_DATA_API_KEY}"
    try:
        res = requests.get(url, timeout=5).json()
        if "values" in res:
            return res["values"]
    except Exception as e:
        print(f"Data fetch error for {symbol}: {e}")
    return None

def analyze_hybrid_scalp(symbol, candles):
    if not candles or len(candles) < 5:
        return None
    
    # Latest Candles (0 is most recent)
    c0 = float(candles[0]["close"])
    o0 = float(candles[0]["open"])
    h0 = float(candles[0]["high"])
    l0 = float(candles[0]["low"])
    
    c1 = float(candles[1]["close"])
    o1 = float(candles[1]["open"])
    
    # 1. Micro-FVG / Gap Detection
    bullish_gap = l0 > float(candles[2]["high"])
    bearish_gap = h0 < float(candles[2]["low"])
    
    # 2. Momentum / Displacement Body
    body_size = abs(c0 - o0)
    prev_body = abs(c1 - o1)
    
    score = 0
    signal_type = None
    
    # Bullish Logic
    if c0 > o0 and (body_size > prev_body or bullish_gap):
        score += 30
        if bullish_gap:
            score += 20
        if c0 > float(candles[1]["high"]):
            score += 15
        signal_type = "BUY"
        
    # Bearish Logic
    elif c0 < o0 and (body_size > prev_body or bearish_gap):
        score += 30
        if bearish_gap:
            score += 20
        if c0 < float(candles[1]["low"]):
            score += 15
        signal_type = "SELL"

    # Scalper Gate Threshold: Score >= 45
    if score >= 45 and signal_type:
        pip_factor = 0.1 if symbol == "XAUUSD" else 0.0001
        sl_pips = 15 if symbol == "XAUUSD" else 7
        tp_pips = 25 if symbol == "XAUUSD" else 12
        
        if signal_type == "BUY":
            sl = round(c0 - (sl_pips * pip_factor), 2 if symbol == "XAUUSD" else 4)
            tp = round(c0 + (tp_pips * pip_factor), 2 if symbol == "XAUUSD" else 4)
        else:
            sl = round(c0 + (sl_pips * pip_factor), 2 if symbol == "XAUUSD" else 4)
            tp = round(c0 - (tp_pips * pip_factor), 2 if symbol == "XAUUSD" else 4)
            
        return {
            "pair": symbol,
            "type": signal_type,
            "entry": c0,
            "sl": sl,
            "tp": tp,
            "score": score
        }
    return None

def scheduled_market_scan():
    global SCANS_TODAY
    SCANS_TODAY += 1
    
    for pair in PAIRS:
        data = fetch_m5_data(pair)
        if data:
            sig = analyze_hybrid_scalp(pair, data)
            if sig:
                msg = (
                    f"⚡ *M5 HYBRID SCALP SIGNAL DETECTED*\n\n"
                    f"• *Pair:* `{sig['pair']}`\n"
                    f"• *Action:* `{sig['type']}`\n"
                    f"• *Entry Price:* `{sig['entry']}`\n"
                    f"• *Stop Loss:* `{sig['sl']}`\n"
                    f"• *Take Profit:* `{sig['tp']}`\n"
                    f"• *Confluence Score:* `{sig['score']}/100`\n\n"
                    f"⚠️ *Execution Mode:* Paper Trade Verification"
                )
                send_telegram_msg(msg)

scheduler = BackgroundScheduler()
scheduler.add_job(scheduled_market_scan, 'interval', minutes=5)
scheduler.start()

# Generic Handler Function
async def process_telegram_update(request: Request):
    try:
        update = await request.json()
        if "message" in update and "text" in update["message"]:
            chat_id = str(update["message"]["chat"]["id"])
            text = update["message"]["text"].strip()

            if text == "/status":
                pht_time = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %I:%M:%S %p PHT")
                msg = (
                    "📊 *ENGINE OPERATIONAL STATUS*\n\n"
                    "• *System Mode:* `HYBRID_SCALPER_15_TRADES_DAY`\n"
                    "• *Paper Session:* `True`\n"
                    "• *Data Provider:* `TWELVE_DATA_SPOT`\n"
                    f"• *Scans Today:* `{SCANS_TODAY}`\n"
                    f"• *Last Scan:* `{pht_time}`"
                )
                send_telegram_msg(msg, chat_id)

            elif text == "/scan":
                send_telegram_msg("🔍 *Scanning M5 Hybrid Scalp setups (XAUUSD, GBPUSD, EURUSD)... Please wait.*", chat_id)
                signals_found = []
                for pair in PAIRS:
                    data = fetch_m5_data(pair)
                    if data:
                        sig = analyze_hybrid_scalp(pair, data)
                        if sig:
                            signals_found.append(sig)
                
                if signals_found:
                    for sig in signals_found:
                        msg = (
                            f"⚡ *HYBRID SCALP SIGNAL*\n\n"
                            f"• *Pair:* `{sig['pair']}` | *Action:* `{sig['type']}`\n"
                            f"• *Entry:* `{sig['entry']}`\n"
                            f"• *SL:* `{sig['sl']}` | *TP:* `{sig['tp']}`\n"
                            f"• *Score:* `{sig['score']}/100`"
                        )
                        send_telegram_msg(msg, chat_id)
                else:
                    send_telegram_msg("ℹ️️ *No M5 Hybrid Scalp setups detected right now.*", chat_id)

            elif text in ["/help", "/start"]:
                msg = (
                    "🤖 *AI TRADING BOT COMMANDS*\n\n"
                    "• `/status` - Check active system mode & scan counts\n"
                    "• `/scan` - Force manual scan for M5 Scalp setups"
                )
                send_telegram_msg(msg, chat_id)

    except Exception as e:
        print(f"Webhook processing error: {e}")
        
    return {"status": "ok"}

# Support pareho ang /telegram-webhook AT /telegram/webhook (GET & POST)
@app.api_route("/telegram-webhook", methods=["GET", "POST"])
@app.api_route("/telegram/webhook", methods=["GET", "POST"])
async def telegram_webhook(request: Request):
    return await process_telegram_update(request)

# Health Endpoint (Supports GET & HEAD)
@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    return {"status": "ok", "mode": "HYBRID_SCALPER"}

@app.get("/status")
def status():
    pht_time = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %I:%M:%S %p PHT")
    return {
        "system_mode": "HYBRID_SCALPER_15_TRADES_DAY",
        "paper_session": True,
        "scans_today": SCANS_TODAY,
        "last_scan_pht": pht_time
    }
