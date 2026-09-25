import os
import time
import requests

# Kunin ang Telegram Credentials mula sa Render Environment Variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Missing Telegram Environment Variables.")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
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
        time.sleep(60) # Maghihintay ng 1 minuto bago ang susunod na check

if __name__ == "__main__":
    start_trading_bot()
