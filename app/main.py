import os
import datetime
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from apscheduler.schedulers.background import BackgroundScheduler
import requests
import pandas as pd
import numpy as np

from scripts.generate_synthetic_data import generate_spot_ohlc

app = FastAPI(title="SMC M15 Killzone Engine")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")

PAIRS = ["XAUUSD", "GBPUSD", "EURUSD"]
SCANS_TODAY = 0

scheduler = BackgroundScheduler()

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

def fetch_m15_data(symbol: str):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=15min&outputsize=30&apikey={TWELVE_DATA_API_KEY}"
    try:
        res = requests.get(url, timeout=5).json()
        if "values" in res:
            return res["values"]
    except Exception as e:
        print(f"Data fetch error for {symbol}: {e}")
    return None

def analyze_m15_killzone_setup(symbol, candles):
    if not candles or len(candles) < 25:
        return None
    
    closes = [float(c["close"]) for c in candles]
    
    # Fast & Slow Trend Confluence (EMA 20 & 50)
    ema20 = sum(closes[:20]) / 20
    ema50 = sum(closes[:25]) / 25

    c0 = float(candles[0]["close"])
    o0 = float(candles[0]["open"])
    h0 = float(candles[0]["high"])
    l0 = float(candles[0]["low"])
    
    c1 = float(candles[1]["close"])
    o1 = float(candles[1]["open"])
    
    # M15 Swing Points for SL Placement
    recent_highs = [float(c["high"]) for c in candles[1:6]]
    recent_lows = [float(c["low"]) for c in candles[1:6]]
    
    body_size = abs(c0 - o0)
    prev_body = abs(c1 - o1)
    
    score = 0
    signal_type = None
    
    # Bullish Trend Alignment
    if c0 > ema20 and ema20 > ema50:
        if c0 > o0 and body_size > prev_body * 1.2:
            score += 40
            if l0 < min(recent_lows):  # Liquidity Grab / Wick Rejection
                score += 30
            if c0 > float(candles[1]["high"]):
                score += 15
            signal_type = "BUY"
        
    # Bearish Trend Alignment
    elif c0 < ema20 and ema20 < ema50:
        if c0 < o0 and body_size > prev_body * 1.2:
            score += 40
            if h0 > max(recent_highs):  # Liquidity Grab / Wick Rejection
                score += 30
            if c0 < float(candles[1]["low"]):
                score += 15
            signal_type = "SELL"

    # M15 Quality Gate
    required_score = 70

    if score >= required_score and signal_type:
        pip_factor = 0.1 if symbol == "XAUUSD" else 0.0001
        
        # Structure-Based SL and Fixed 1:3 RR TP
        if symbol == "XAUUSD":
            sl_pips = max(25, round(abs(c0 - min(recent_lows if signal_type == "BUY" else recent_highs)) / pip_factor, 1))
            tp_pips = sl_pips * 3.0
        else: # GBPUSD & EURUSD
            sl_pips = max(10, round(abs(c0 - min(recent_lows if signal_type == "BUY" else recent_highs)) / pip_factor, 1))
            tp_pips = sl_pips * 3.0
        
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

def run_hybrid_backtest_task(chat_id: str):
    send_telegram_msg("⏳ *Running M15 High-Timeframe Killzone Backtest (7-Day Replay)...*", chat_id)
    try:
        np.random.seed(42)
        
        summary_msg = "📊 *M15 KILLZONE STRATEGY BACKTEST (7-Day Replay | 1:3 RR)*\n\n"
        for pair in PAIRS:
            # Using M15 generated data structure
            _, _, df_m15, _ = generate_spot_ohlc(pair, days=7)
            
            total_trades = 0
            wins = 0
            losses = 0
            net_r = 0.0
            
            records = df_m15.to_dict('records')
            for i in range(len(records) - 30, 5, -1):
                window = records[i:i+25]
                sig = analyze_m15_killzone_setup(pair, window)
                if sig:
                    total_trades += 1
                    future_candles = records[max(0, i-15):i]
                    win = False
                    for fc in future_candles:
                        if sig['type'] == "BUY" and float(fc['high']) >= sig['tp']:
                            win = True
                            break
                        elif sig['type'] == "SELL" and float(fc['low']) <= sig['tp']:
                            win = True
                            break
                    
                    if win:
                        wins += 1
                        net_r += 3.0  # Strict 1:3 RR Target
                    else:
                        losses += 1
                        net_r -= 1.0
            
            win_rate = round((wins / total_trades * 100), 1) if total_trades > 0 else 0.0
            expectancy = round(net_r / total_trades, 2) if total_trades > 0 else 0.0
            
            summary_msg += (
                f"• *{pair}*:\n"
                f"  - Trades: `{total_trades}` | Win Rate: `{win_rate}%`\n"
                f"  - Net R: `{round(net_r, 1)}R` | Expectancy: `{expectancy}R`\n\n"
            )
        send_telegram_msg(summary_msg, chat_id)
    except Exception as err:
        send_telegram_msg(f"❌ Backtest Error: {err}", chat_id)

def scheduled_market_scan():
    global SCANS_TODAY
    SCANS_TODAY += 1
    
    for pair in PAIRS:
        data = fetch_m15_data(pair)
        if data:
            sig = analyze_m15_killzone_setup(pair, data)
            if sig:
                msg = (
                    f"⚡ *M15 KILLZONE SIGNAL DETECTED*\n\n"
                    f"• *Pair:* `{sig['pair']}`\n"
                    f"• *Action:* `{sig['type']}`\n"
                    f"• *Entry Price:* `{sig['entry']}`\n"
                    f"• *Stop Loss:* `{sig['sl']}`\n"
                    f"• *Take Profit:* `{sig['tp']}` (1:3 RR)\n"
                    f"• *Confluence Score:* `{sig['score']}/100`\n\n"
                    f"⚠️ *Execution Mode:* Paper Trade Verification"
                )
                send_telegram_msg(msg)

@app.on_event("startup")
def startup_event():
    if not scheduler.running:
        scheduler.add_job(scheduled_market_scan, 'interval', minutes=15)
        scheduler.start()

@app.api_route("/telegram-webhook", methods=["GET", "POST"])
@app.api_route("/telegram/webhook", methods=["GET", "POST"])
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        update = await request.json()
        if "message" in update and "text" in update["message"]:
            chat_id = str(update["message"]["chat"]["id"])
            text = update["message"]["text"].strip()

            if text == "/status":
                pht_time = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %I:%M:%S %p PHT")
                msg = (
                    "📊 *ENGINE OPERATIONAL STATUS*\n\n"
                    "• *System Mode:* `M15_KILLZONE_PRODUCTION`\n"
                    "• *Paper Session:* `True`\n"
                    "• *Data Provider:* `TWELVE_DATA_SPOT`\n"
                    f"• *Scans Today:* `{SCANS_TODAY}`\n"
                    f"• *Last Scan:* `{pht_time}`"
                )
                send_telegram_msg(msg, chat_id)

            elif text == "/scan":
                send_telegram_msg("🔍 *Scanning M15 High-Confluence setups... Please wait.*", chat_id)
                signals_found = []
                for pair in PAIRS:
                    data = fetch_m15_data(pair)
                    if data:
                        sig = analyze_m15_killzone_setup(pair, data)
                        if sig:
                            signals_found.append(sig)
                
                if signals_found:
                    for sig in signals_found:
                        msg = (
                            f"⚡ *M15 KILLZONE SIGNAL*\n\n"
                            f"• *Pair:* `{sig['pair']}` | *Action:* `{sig['type']}`\n"
                            f"• *Entry:* `{sig['entry']}`\n"
                            f"• *SL:* `{sig['sl']}` | *TP:* `{sig['tp']}`\n"
                            f"• *Score:* `{sig['score']}/100`"
                        )
                        send_telegram_msg(msg, chat_id)
                else:
                    send_telegram_msg("ℹ *No high-confluence M15 setups detected right now.*", chat_id)

            elif text == "/backtest":
                background_tasks.add_task(run_hybrid_backtest_task, chat_id)

            elif text in ["/help", "/start"]:
                msg = (
                    "🤖 *AI TRADING BOT COMMANDS*\n\n"
                    "• `/status` - Check active system mode & scan counts\n"
                    "• `/scan` - Force manual scan for M15 setups\n"
                    "• `/backtest` - Run instant strategy simulation"
                )
                send_telegram_msg(msg, chat_id)

    except Exception as e:
        print(f"Webhook processing error: {e}")
        
    return {"status": "ok"}

@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    return {"status": "ok", "mode": "M15_KILLZONE"}

@app.get("/status")
def status():
    pht_time = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %I:%M:%S %p PHT")
    return {
        "system_mode": "M15_KILLZONE_PRODUCTION",
        "paper_session": True,
        "scans_today": SCANS_TODAY,
        "last_scan_pht": pht_time
    }
