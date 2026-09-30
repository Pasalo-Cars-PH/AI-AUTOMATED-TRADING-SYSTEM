import os
import time
import threading
import requests
import yfinance as yf
import pandas as pd
import ta
from fastapi import FastAPI

app = FastAPI()

# GATED HARD-LOCK ENGINE (PAPER MODE ONLY)
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
    # STRICT EXECUTION LOCK: Automatic NO TRADE if KILL_SWITCH is True or MASTER_ENABLE is False
    if KILL_SWITCH or not MASTER_ENABLE:
        return {"symbol": "NONE", "action": "NONE", "reason": "STRICT_EXECUTION_LOCK_ACTIVE"}
    
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

def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram error: {e}")

def run_bot():
    send_telegram_alert(
        "🛡️ *GATED EXECUTION SYSTEM LOADED*\n\n"
        "• Mode: `PAPER FIRST`\n"
        "• Master Enable: `FALSE`\n"
        "• Kill Switch: `ACTIVE (TRUE)`\n"
        "• Status: All live signals locked until full gate pass."
    )

bot_thread = threading.Thread(target=run_bot, daemon=True)
bot_thread.start()
