import threading
import time
import uvicorn
from fastapi import FastAPI
from app.config import settings
from app.database.models import init_db

app = FastAPI(title="Quant Automated Trading Engine", version="2.0.0")

# Initialize Database Engine
init_db()

@app.get("/")
def root():
    return {"status": "ONLINE", "engine": "Quant Automated Trading Engine v2.0"}

@app.get("/health")
def health_check():
    return {
        "status": "ok" if not settings.KILL_SWITCH and settings.MASTER_ENABLE else "degraded",
        "master_enable": settings.MASTER_ENABLE,
        "kill_switch": settings.KILL_SWITCH,
        "trading_mode": settings.TRADING_MODE,
        "database": "sqlite_connected",
        "telegram": "configured" if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID else "misconfigured",
        "timestamp": time.time()
    }

def trading_engine_loop():
    print("🚀 Background Quantitative Trading Engine Thread Started...")
    while True:
        if settings.KILL_SWITCH or not settings.MASTER_ENABLE:
            print("🛑 Engine Paused by Safety Gate (Kill Switch Active or Master Disabled)")
        else:
            print("🔍 Engine Scanning Markets...")
        time.sleep(60)

# Start background strategy engine thread alongside FastAPI server
threading.Thread(target=trading_engine_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)
