import os
import time
import threading
import requests
import yfinance as yf
import pandas as pd
import ta
from fastapi import FastAPI

# Import ang gated decision engine mula sa gates.py
from app.gates import evaluate_trade_candidate, check_data_quality

app = FastAPI()

# 🛡️ STRICT EXECUTION HARD-LOCK (PAPER MODE ONLY)
MASTER_ENABLE = False
KILL_SWITCH = True
TRADING_MODE = "PAPER"

latest_trade_signal = {
    "symbol": "NONE",
    "action": "NONE",
    "sl": 0.0,
    "tp": 0.0,
    "mode": TRADING_MODE
}

@app.api_route("/", methods=["GET", "HEAD"])
@app.api_route("/health", methods=["GET", "HEAD"])
def health_check():
    return {
        "status": "ok", 
        "mode": TRADING_MODE, 
        "master_enable": MASTER_ENABLE, 
        "kill_switch": KILL_SWITCH
    }

@app.get("/signal")
def get_signal():
    global latest_trade_signal
    # STRICT EXECUTION LOCK: Rejects live execution while hard-locked
    if KILL_SWITCH or not MASTER_ENABLE:
        return {
            "symbol": "NONE", 
            "action": "NONE", 
            "reason": "STRICT_EXECUTION_LOCK_ACTIVE",
            "mode": TRADING_MODE
        }
    
    response = latest_trade_signal.copy()
    if latest_trade_signal["action"] != "NONE":
        latest_trade_signal = {"symbol": "NONE", "action": "NONE", "sl": 0.0, "tp": 0.0, "mode": TRADING_MODE}
    return response

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

SYMBOLS = {
    "BTC-USD": {"name": "Bitcoin (Crypto)", "mt5_symbol": "BTCUSD"},
    "GC=F": {"name": "Gold (Commodity)", "mt5_symbol": "XAUUSD"},
    "EURUSD=X": {"name": "EUR/USD (Forex)", "mt5_symbol": "EURUSD"}
}
TIMEFRAME = "5m"
CHECK_INTERVAL = 60

def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram alert error: {e}")

def analyze_and_gate_symbol(symbol, info):
    global latest_trade_signal
    name = info["name"]
    mt5_symbol = info["mt5_symbol"]

    # 1. Fetch 5M Candle Data
    df = yf.download(tickers=symbol, period="5d", interval=TIMEFRAME, progress=False)
    
    # Gate Check: Data Quality
    data_ok, data_reason = check_data_quality(df)
    if not data_ok:
        print(f"[{symbol}] Data Quality Failed: {data_reason}")
        return

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Indicators setup
    df['EMA_9'] = ta.trend.ema_indicator(df['Close'], window=9)
    df['EMA_21'] = ta.trend.ema_indicator(df['Close'], window=21)
    df['EMA_55'] = ta.trend.ema_indicator(df['Close'], window=55)
    df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
    df['ATR'] = ta.volatility.average_true_range(df['High'], df['Low'], df['Close'], window=14)

    latest = df.iloc[-1]
    previous = df.iloc[-2]

    current_price = float(latest['Close'])
    ema_9 = float(latest['EMA_9'])
    ema_21 = float(latest['EMA_21'])
    ema_55 = float(latest['EMA_55'])
    rsi = float(latest['RSI'])
    atr = float(latest['ATR'])

    prev_ema_9 = float(previous['EMA_9'])
    prev_ema_21 = float(previous['EMA_21'])

    m5_action = "NONE"

    # Candidate Entry Trigger
    if prev_ema_9 < prev_ema_21 and ema_9 > ema_21 and current_price > ema_55:
        m5_action = "BUY"
    elif prev_ema_9 > prev_ema_21 and ema_9 < ema_21 and current_price < ema_55:
        m5_action = "SELL"

    if m5_action != "NONE":
        # 2. Pass Candidate Trade Through 15-Gate Pipeline
        gate_result, confluence_score = evaluate_trade_candidate(
            symbol=symbol,
            m5_action=m5_action,
            price=current_price,
            ema55=ema_55,
            rsi=rsi,
            atr=atr
        )

        sl = current_price - (atr * 1.5) if m5_action == "BUY" else current_price + (atr * 1.5)
        tp = current_price + (atr * 3.0) if m5_action == "BUY" else current_price - (atr * 3.0)

        # 3. Handle Gate Outcomes
        if gate_result == "ACTIONABLE_PAPER_PASS":
            msg = (
                f"📝 *PAPER EXECUTED (ACTIONABLE SETUP)*\n\n"
                f"📊 *Asset:* `{symbol}` ({name})\n"
                f"🎯 *Direction:* `{m5_action}`\n"
                f"💰 *Entry:* `${current_price:.4f}`\n"
                f"🔴 *SL:* `${sl:.4f}` | 🟢 *TP:* `${tp:.4f}`\n"
                f"💯 *Confluence Score:* `{confluence_score}/100`\n"
                f"🔒 *Execution Lock:* `PAPER LOGGED ONLY`"
            )
            send_telegram_alert(msg)
        else:
            # Audit log for rejected trades
            msg = (
                f"🛑 *TRADE REJECTED BY GATE SYSTEM*\n\n"
                f"📊 *Asset:* `{symbol}` ({name})\n"
                f"🔎 *Candidate Action:* `{m5_action}`\n"
                f"⛔ *Failed Gate:* `{gate_result}`\n"
                f"💯 *Score:* `{confluence_score}/100` (Required: >= 75)\n"
                f"⏱️ *Status:* NO TRADE"
            )
            send_telegram_alert(msg)

def run_bot():
    send_telegram_alert(
        "🛡️ *GATED EXECUTION ENGINE ACTIVE (PAPER MODE)*\n\n"
        "• Hard Lock: `ENGAGED`\n"
        "• Target Logs: Paper Audit Trail\n"
        "• Monitoring: `BTC-USD`, `GC=F`, `EURUSD=X`"
    )
    
    while True:
        try:
            for symbol, info in SYMBOLS.items():
                analyze_and_gate_symbol(symbol, info)
        except Exception as e:
            print(f"Loop error: {e}")
            
        time.sleep(CHECK_INTERVAL)

bot_thread = threading.Thread(target=run_bot, daemon=True)
bot_thread.start()
