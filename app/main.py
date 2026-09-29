import os
import time
import threading
import requests
import yfinance as yf
import pandas as pd
import ta
import uvicorn
from fastapi import FastAPI

# --- FASTAPI SERVER PARA SA RENDER AT UPTIMEROBOT ---
app = FastAPI()

# Global variable para sa active trade signal na kukunin ng MT5 EA
latest_trade_signal = {
    "symbol": "NONE",
    "action": "NONE",
    "sl": 0.0,
    "tp": 0.0
}

@app.api_route("/", methods=["GET", "HEAD"])
@app.api_route("/health", methods=["GET", "HEAD"])
def health_check():
    return {"status": "ok", "message": "Trading bot is running"}

@app.get("/signal")
def get_signal():
    """
    Endpoint na pinagpo-poll ng MT5 EA (RenderBridge) bawat second
    """
    global latest_trade_signal
    response = latest_trade_signal.copy()
    
    # I-reset ang signal kapag naipasa na sa MT5 para maiwasan ang paulit-ulit na trade execution
    if latest_trade_signal["action"] != "NONE":
        latest_trade_signal = {"symbol": "NONE", "action": "NONE", "sl": 0.0, "tp": 0.0}
        
    return response

# --- ENVIRONMENT VARIABLES ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# --- MULTI-ASSET CONFIGURATION ---
# Mapping YFinance Symbol -> MT5 Broker Symbol Name
SYMBOLS = {
    "BTC-USD": {"name": "Bitcoin (Crypto)", "mt5_symbol": "BTCUSD"},
    "XAUUSD=X": {"name": "Gold (Spot)", "mt5_symbol": "XAUUSD"},
    "EURUSD=X": {"name": "EUR/USD (Forex)", "mt5_symbol": "EURUSD"}
}
TIMEFRAME = "5m"       # Pinalitan sa 5M para sa fast scalping/day trading
CHECK_INTERVAL = 60    # Chino-check ang market bawat 60 seconds (1 minute)

def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Missing Telegram credentials.")
        return
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")

def analyze_symbol(symbol, info):
    global latest_trade_signal
    name = info["name"]
    mt5_symbol = info["mt5_symbol"]

    try:
        # Gamitin ang Ticker history para maiwasan ang 401 Unauthorized block ng Yahoo
        ticker_obj = yf.Ticker(symbol)
        df = ticker_obj.history(period="5d", interval=TIMEFRAME)
    except Exception as err:
        print(f"[{symbol}] Error fetching data: {err}")
        return
    
    if df.empty or len(df) < 55:
        print(f"[{symbol}] Insufficient market data or market closed.")
        return

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Calculate Triple EMA (9, 21, 55) at ATR para sa Dynamic SL/TP
    df['EMA_9'] = ta.trend.ema_indicator(df['Close'], window=9)
    df['EMA_21'] = ta.trend.ema_indicator(df['Close'], window=21)
    df['EMA_55'] = ta.trend.ema_indicator(df['Close'], window=55)
    df['ATR'] = ta.volatility.average_true_range(df['High'], df['Low'], df['Close'], window=14)

    latest = df.iloc[-1]
    previous = df.iloc[-2]

    current_price = float(latest['Close'])
    ema_9 = float(latest['EMA_9'])
    ema_21 = float(latest['EMA_21'])
    ema_55 = float(latest['EMA_55'])
    
    prev_ema_9 = float(previous['EMA_9'])
    prev_ema_21 = float(previous['EMA_21'])
    
    atr = float(latest['ATR'])

    print(f"[{symbol}] Price: {current_price:.4f} | EMA9: {ema_9:.4f} | EMA21: {ema_21:.4f} | EMA55: {ema_55:.4f}")

    # 🟢 BUY CONDITION: EMA 9 crosses ABOVE EMA 21 WHILE Price & EMA 9 are ABOVE EMA 55
    if prev_ema_9 < prev_ema_21 and ema_9 > ema_21 and current_price > ema_55:
        sl = current_price - (atr * 1.5)
        tp = current_price + (atr * 3.0)
        
        # Save signal para sa MT5 EA execution
        latest_trade_signal = {
            "symbol": mt5_symbol,
            "action": "BUY",
            "sl": round(sl, 4),
            "tp": round(tp, 4)
        }
        
        msg = (
            f"🚀 *HIGH-PROBABILITY TRIPLE EMA BUY SIGNAL*\n\n"
            f"📊 *Asset:* `{symbol}` ({name})\n"
            f"💰 *Entry Price:* `${current_price:.4f}`\n"
            f"🔴 *Stop Loss (SL):* `${sl:.4f}`\n"
            f"🟢 *Take Profit (TP):* `${tp:.4f}`\n\n"
            f"📈 *Trend:* EMA 9 & 21 Cross Above EMA 55 (Bullish Crossover)\n"
            f"⚡ *Timeframe:* 5-Minute Scalp\n"
            f"🛡️ *Risk/Reward:* 1:2 Ratio"
        )
        send_telegram_alert(msg)

    # 🔴 SELL CONDITION: EMA 9 crosses BELOW EMA 21 WHILE Price & EMA 9 are BELOW EMA 55
    elif prev_ema_9 > prev_ema_21 and ema_9 < ema_21 and current_price < ema_55:
        sl = current_price + (atr * 1.5)
        tp = current_price - (atr * 3.0)
        
        # Save signal para sa MT5 EA execution
        latest_trade_signal = {
            "symbol": mt5_symbol,
            "action": "SELL",
            "sl": round(sl, 4),
            "tp": round(tp, 4)
        }
        
        msg = (
            f"🔻 *HIGH-PROBABILITY TRIPLE EMA SELL SIGNAL*\n\n"
            f"📊 *Asset:* `{symbol}` ({name})\n"
            f"💰 *Entry Price:* `${current_price:.4f}`\n"
            f"🔴 *Stop Loss (SL):* `${sl:.4f}`\n"
            f"🟢 *Take Profit (TP):* `${tp:.4f}`\n\n"
            f"📉 *Trend:* EMA 9 & 21 Cross Below EMA 55 (Bearish Crossover)\n"
            f"⚡ *Timeframe:* 5-Minute Scalp\n"
            f"🛡️ *Risk/Reward:* 1:2 Ratio"
        )
        send_telegram_alert(msg)

def run_bot():
    send_telegram_alert(
        "🤖 *Triple EMA Strategy Engine Activated*\n\n"
        "Currently Monitoring (5M Timeframe):\n"
        "• 🟡 `BTC-USD` (Bitcoin)\n"
        "• 🏆 `XAUUSD=X` (Gold)\n"
        "• 💶 `EURUSD=X` (EUR/USD)\n\n"
        "⏱️ Interval: `1m check` | Strategy: `Triple EMA (9, 21, 55) + ATR`"
    )
    
    while True:
        try:
            for symbol, info in SYMBOLS.items():
                analyze_symbol(symbol, info)
        except Exception as e:
            print(f"Error encountered: {e}")
            
        time.sleep(CHECK_INTERVAL)

# I-start ang background thread para sa trading loop
bot_thread = threading.Thread(target=run_bot, daemon=True)
bot_thread.start()
