import os
import threading
import time
import uuid
from datetime import datetime, timezone
import uvicorn
from fastapi import FastAPI

from app.config import settings
from app.database.models import init_db
from app.data.providers.binance_adapter import BinanceDataProvider
from app.data.validator import DataValidator
from app.data.normalizer import DataQualityState
from app.indicators.ema import EMAIndicator
from app.indicators.rsi import RSIIndicator
from app.indicators.atr import ATRIndicator
from app.structure.market_structure import MarketStructureEngine
from app.strategies.setup_engine import SetupEngine
from app.scoring.confluence import ConfluenceEngine
from app.execution.paper import PaperExecutionProvider
from app.execution.schemas import OrderRequest
from app.execution.order_validator import PreTradeValidator
from app.notifications.telegram import TelegramDispatcher

app = FastAPI(title="Quant Automated Trading Engine", version="2.0.0")

init_db()

execution_provider = PaperExecutionProvider(initial_balance=10000.0)
telegram_dispatcher = TelegramDispatcher()
market_data_provider = BinanceDataProvider()

SYMBOLS_TO_SCAN = ["BTCUSD", "ETHUSD"]

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
        "telegram": telegram_dispatcher.inspect_health(),
        "timestamp": time.time()
    }

def process_market_scan(symbol: str):
    signal_id = f"SIG_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:4].upper()}"

    candles = market_data_provider.fetch_ohlcv(symbol, timeframe="M15", limit=200)
    if DataValidator.validate_candles(candles) != DataQualityState.CONFIRMED_DATA:
        return

    ema_results = EMAIndicator.calculate(candles, [20, 50, 100, 200])
    rsi_result = RSIIndicator.calculate(candles, window=14)
    atr_result = ATRIndicator.calculate(candles, window=14)
    indicators = {**ema_results}
    if rsi_result: indicators["RSI_14"] = rsi_result
    if atr_result: indicators["ATR_14"] = atr_result

    structure = MarketStructureEngine.analyze(candles)
    candidate = SetupEngine.evaluate_setups(candles, indicators, structure)
    if not candidate:
        return

    score = ConfluenceEngine.calculate_score(
        setup=candidate, indicators=indicators, structure=structure,
        mtf_score=9, rr_ratio=2.0, data_quality=DataQualityState.CONFIRMED_DATA
    )

    if not score.is_actionable:
        return

    req = OrderRequest(
        signal_id=signal_id,
        symbol=symbol,
        direction=candidate.direction.value,
        volume=0.01,
        entry_price=candidate.trigger_level,
        stop_loss=candidate.invalidation_level,
        take_profit=candidate.trigger_level + 2.0 * (atr_result.value if atr_result else 10.0)
    )

    acc = execution_provider.get_account()
    validation = PreTradeValidator.pre_trade_check(req, acc.equity, current_spread=0.0002)

    if not validation["approved"]:
        print(f"[{symbol}] ⛔ Pre-Trade Rejection: {validation['rejection_reasons']}")
        return

    exec_result = execution_provider.place_market_order(req)
    telegram_dispatcher.dispatch_actionable_signal({
        "signal_id": signal_id,
        "symbol": symbol,
        "direction": req.direction,
        "entry": req.entry_price,
        "stop_loss": req.stop_loss,
        "take_profit": req.take_profit,
        "score": score.total_score
    })
    print(f"[{symbol}] 🚀 Order Executed: {exec_result.order_id}")

def trading_engine_loop():
    print("🚀 Background Quantitative Trading Engine Thread Started...")
    while True:
        if settings.KILL_SWITCH or not settings.MASTER_ENABLE:
            print("🛑 Engine Paused by Safety Gate")
        else:
            print("🔍 Scanning Markets...")
            for symbol in SYMBOLS_TO_SCAN:
                try:
                    process_market_scan(symbol)
                except Exception as e:
                    print(f"[Engine Error] {e}")
        time.sleep(60)

threading.Thread(target=trading_engine_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)
