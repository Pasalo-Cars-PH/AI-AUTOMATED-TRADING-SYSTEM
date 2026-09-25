import threading
import time
from fastapi import FastAPI
from app.main import TradingEngineOrchestrator

app = FastAPI(title="Quant Engine Service", version="1.0.0")
orchestrator = TradingEngineOrchestrator()

SYMBOLS_TO_MONITOR = ["BTCUSD", "ETHUSD"]

def background_trading_loop():
    while True:
        try:
            for symbol in SYMBOLS_TO_MONITOR:
                result = orchestrator.process_symbol(symbol)
                print(f"[Engine Loop] {symbol} Processed -> Status: {result.get('status')}")
        except Exception as e:
            print(f"[Engine Loop Error] {e}")
        time.sleep(300)  # Run every 5 minutes

# Start background worker thread
threading.Thread(target=background_trading_loop, daemon=True).start()

@app.get("/health")
def health_check():
    return {"status": "HEALTHY", "engine": "RUNNING", "environment": "PRODUCTION"}

@app.get("/status")
def status_check():
    acc = orchestrator.execution.get_account_state()
    return {
        "account_equity": acc.equity,
        "account_balance": acc.balance,
        "open_positions": acc.open_positions_count,
        "telegram_status": orchestrator.telegram.inspect_health().value
    }
