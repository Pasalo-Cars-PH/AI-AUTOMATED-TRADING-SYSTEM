import os
import time
import requests
import yfinance as yf
import pandas as pd
import ta

# Environment Variables
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Multi-Asset Configuration
SYMBOLS = {
    "BTC-USD": "Bitcoin (Crypto)",
    "XAUUSD=X": "Gold (Commodity)",
    "EURUSD=X": "EUR/USD (Forex)"
}
TIMEFRAME = "15m"      # 15-minute timeframe
CHECK_INTERVAL = 300   # Check every 5 minutes (300 seconds)

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

def analyze_symbol(symbol, name):
    # Fetch historical market data
    df = yf.download(tickers=symbol, period="5d", interval=TIMEFRAME, progress=False)
    
    if df.empty or len(df) < 200:
        print(f"[{symbol}] Insufficient market data or market closed.")
        return

    # Flatten columns if multi-index
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Calculate Technical Indicators
    df['EMA_200'] = ta.trend.ema_indicator(df['Close'], window=200)
    df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
    df['ATR'] = ta.volatility.average_true_range(df['High'], df['Low'], df['Close'], window=14)

    # Latest Candle Data
    latest = df.iloc[-1]
    previous = df.iloc[-2]

    current_price = float(latest['Close'])
    ema_200 = float(latest['EMA_200'])
    rsi = float(latest['RSI'])
    prev_rsi = float(previous['RSI'])
    atr = float(latest['ATR'])

    print(f"[{symbol}] Price: {current_price:.4f} | EMA 200: {ema_200:.4f} | RSI: {rsi:.2f}")

    # BUY SIGNAL LOGIC: Uptrend (Price > EMA200) + RSI Reversal from Oversold (< 40)
    if current_price > ema_200 and prev_rsi < 40 and rsi >= 40:
        sl = current_price - (atr * 1.5)
        tp = current_price + (atr * 3.0)
        
        msg = (
            f"🚀 *HIGH-PROBABILITY BUY SIGNAL*\n\n"
            f"📊 *Asset:* `{symbol}` ({name})\n"
            f"💰 *Entry Price:* `${current_price:.4f}`\n"
            f"🔴 *Stop Loss (SL):* `${sl:.4f}`\n"
            f"🟢 *Take Profit (TP):* `${tp:.4f}`\n\n"
            f"📈 *Trend:* Above 200 EMA (Bullish)\n"
            f"⚡ *RSI:* {rsi:.1f} (Bouncing from Oversold)\n"
            f"🛡️ *Risk/Reward:* 1:2 Ratio"
        )
        send_telegram_alert(msg)

    # SELL SIGNAL LOGIC: Downtrend (Price < EMA200) + RSI Reversal from Overbought (> 60)
    elif current_price < ema_200 and prev_rsi > 60 and rsi <= 60:
        sl = current_price + (atr * 1.5)
        tp = current_price - (atr * 3.0)
        
        msg = (
            f"🔻 *HIGH-PROBABILITY SELL SIGNAL*\n\n"
            f"📊 *Asset:* `{symbol}` ({name})\n"
            f"💰 *Entry Price:* `${current_price:.4f}`\n"
            f"🔴 *Stop Loss (SL):* `${sl:.4f}`\n"
            f"🟢 *Take Profit (TP):* `${tp:.4f}`\n\n"
            f"📉 *Trend:* Below 200 EMA (Bearish)\n"
            f"⚡ *RSI:* {rsi:.1f} (Rejecting from Overbought)\n"
            f"🛡️ *Risk/Reward:* 1:2 Ratio"
        )
        send_telegram_alert(msg)

def main():
    send_telegram_alert(
        "🤖 *Multi-Asset Strategy Engine Activated*\n\n"
        "Currently Monitoring:\n"
        "• 🟡 `BTC-USD` (Bitcoin)\n"
        "• 🏆 `XAUUSD=X` (Gold)\n"
        "• 💶 `EURUSD=X` (EUR/USD)\n\n"
        "⏱️ Timeframe: `15m` | Strategy: `EMA200 + RSI + ATR`"
    )
    
    while True:
        try:
            for symbol, name in SYMBOLS.items():
                analyze_symbol(symbol, name)
        except Exception as e:
            print(f"Error encountered: {e}")
            
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
