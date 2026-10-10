from fastapi import Request
import os
import requests

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHANNEL_ID")

def send_to_telegram(msg: str):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("No TG creds")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(e)

async def tradingview_webhook(request: Request):
    try:
        body = await request.body()
        text = body.decode('utf-8')
    except:
        data = await request.json()
        text = str(data)

    # AI LEARNING FILTER - hindi isesend pag mababa score
    if "Score=" in text or "SCORE:" in text:
        try:
            # hahanapin 10/10, 8/10, etc
            import re
            m = re.search(r'(\d+)\s*/\s*10', text)
            if m:
                score = int(m.group(1))
                if score < 7:
                    print(f"Filtered low score {score}")
                    return {"status": f"filtered score {score} - weak"}
        except:
            pass

    final_msg = f"🤖 *SuperTradingAI V3 - LIVE*\n\n{text}\n\n_Real Market: OANDA 5m confirm | Bot: ai-trading-bot-v2-8p0y_"
    send_to_telegram(final_msg)
    return {"status": "sent to telegram"}
