import os
import time
import requests

# Kunin ang Telegram Credentials mula sa Render Environment Variables
TELEGRAM_BOT_TOKEN = os.getenv("8981586714:AAHXdcHfx-ttRTw9MzSNPn13B06w8HGgHkI")
TELEGRAM_CHAT_ID = os.getenv("6759636129")

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Missing Telegram Environment Variables.")
        return
    
    url = f"https://api.telegram.org/bot{8981586714:AAHXdcHfx-ttRTw9MzSNPn13B06w8HGgHkI}/sendMessage"
    payload = {
        "chat_id": 6759636129,
        "text": message
    }
    try:
        response = requests.post(url, json=payload)
        print(f"Telegram Notification Sent: {response.status_code}")
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")

def start_trading_bot():
    print("🚀 AI Automated Trading System Initialized...")
    send_telegram_message("🚀 AI Automated Trading System is now LIVE on Render.com!")
    
    # Simple Continuous Loop
    while True:
        print(" Analyzing market conditions...")
        # Dito lalagay ang trading strategy/paper-trading logic
        time.sleep(60) # Maghihintay ng 1 minuto bago ang susunod na check

if __name__ == "__main__":
    start_trading_bot()
