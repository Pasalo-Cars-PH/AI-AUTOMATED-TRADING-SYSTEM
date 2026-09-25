import os
import threading
import time
import uuid
from datetime import datetime, timezone
import uvicorn
from fastapi import FastAPI

from app.config import settings
from app.database.models import init_db

# Engine Imports (Phases 1 - 11)
from app.data.providers.binance_adapter import BinanceDataProvider
from app.data.validator import DataValidator
from app.data.normalizer import DataQualityState
from app.indicators.ema import EMAIndicator
from app.indicators.rsi import RSIIndicator
from app.indicators.atr import ATRIndicator
from app.indicators.vwap import VWAPIndicator
from app.indicators.adx import ADXIndicator
from app.structure.market_structure import MarketStructureEngine
from app.strategies.setup_engine import SetupEngine
from app.scoring.confluence import ConfluenceEngine
from app.risk.risk_engine import RiskEngine
from app.news.news_filter import NewsFilter
from app.structure.m5_confirmation import M5ConfirmationEngine
from app.state.duplicate_detector import DuplicateDetector
from app.execution.paper import PaperExecutionProvider
from app.notifications.telegram import TelegramDispatcher

app = FastAPI(title="Quant Automated Trading Engine", version="2.0.0")

# Initialize Database Engine
init_db()

# Initialize Services
execution_provider = PaperExecutionProvider(initial_balance=10000.0)
telegram_dispatcher = TelegramDispatcher()
market_data_provider = BinanceDataProvider()

# Set crypto symbols for Binance Data Provider (No YFinance dependency)
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
        "telegram": telegram_dispatcher.inspect_health().value,
        "timestamp": time.time()
    }

def process_market_scan(symbol: str):
    signal_id = f"SIG_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:4].upper()}"

    # Step 1: Fetch & Validate Normalized Data
    m15_candles = market_data_provider.fetch_ohlcv(symbol, timeframe="M15", limit=200)
    data_quality = DataValidator.validate_candles(m15_candles)
    if data_quality != DataQualityState.CONFIRMED_DATA:
        print(f"[{symbol}] ❌ Data Quality Gate Failed: {data_quality.value}")
        return

    # Step 2: Calculate Technical Indicators
    ema_results = EMAIndicator.calculate(m15_candles, [20, 50, 100, 200])
    rsi_result = RSIIndicator.calculate(m15_candles, window=14)
    atr_result = ATRIndicator.calculate(m15_candles, window=14)
    vwap_result = VWAPIndicator.calculate(m15_candles)
    adx_result = ADXIndicator.calculate(m15_candles, window=14)

    indicators = {**ema_results}
    if rsi_result: indicators["RSI_14"] = rsi_result
    if atr_result: indicators["ATR_14"] = atr_result
    if vwap_result: indicators["VWAP"] = vwap_result
    if adx_result: indicators["ADX_14"] = adx_result

    # Step 3: Market Structure Analysis
    structure = MarketStructureEngine.analyze(m15_candles)

    # Step 4: Evaluate Candidate Setups
    candidate = SetupEngine.evaluate_setups(m15_candles, indicators, structure)
    if not candidate:
        print(f"[{symbol}] ℹ️ No candidate setup found.")
        return

    # Step 5: Duplicate Protection Check
    ts_bucket = datetime.now(timezone.utc).strftime("%Y%m%d_%H")
    sig_hash = DuplicateDetector.generate_hash(
        symbol, candidate.direction.value, candidate.strategy_name, candidate.trigger_level, ts_bucket
    )
    if DuplicateDetector.is_duplicate(sig_hash):
        print(f"[{symbol}] ⚠️ Duplicate signal detected. Skipping.")
        return

    # Step 6: Confluence Scoring Matrix (75+)
    score_breakdown = ConfluenceEngine.calculate_score(
        setup=candidate,
        indicators=indicators,
        structure=structure,
        mtf_score=9,
        rr_ratio=2.0,
        data_quality=data_quality
    )

    if not score_breakdown.is_actionable:
        print(f"[{symbol}] ⏸️ Score: {score_breakdown.total_score}/100. Below threshold.")
        return

    # Step 7: Risk Management & Position Sizing
    account_state = execution_provider.get_account_state()
    active_positions = execution_provider.get_open_positions()
    atr_val = atr_result.value if atr_result else 10.0

    risk_result = RiskEngine.calculate_position(
        account_equity=account_state.equity,
        entry=candidate.trigger_level,
        stop_loss=candidate.invalidation_level,
        direction=candidate.direction.value,
        symbol=symbol,
        active_positions=active_positions,
        atr=atr_val
    )

    if not risk_result.is_valid:
        print(f"[{symbol}] ❌ Risk Gate Rejection: {risk_result.rejection_reason}")
        return

    # Step 8: News Filter Gate
    news_check = NewsFilter.check_news_risk(symbol)
    if not news_check.is_safe_to_trade:
        print(f"[{symbol}] ❌ News Gate Rejection: {news_check.reasoning}")
        return

    # Step 9: M5 Confirmation Gate
    m5_candles = market_data_provider.fetch_ohlcv(symbol, timeframe="M5", limit=20)
    m5_confirm = M5ConfirmationEngine.validate_m5_close(
        m5_candles=m5_candles,
        setup_zone_high=candidate.setup_zone_high,
        setup_zone_low=candidate.setup_zone_low,
        direction=candidate.direction.value
    )

    if not m5_confirm.confirmed:
        print(f"[{symbol}] ❌ M5 Gate Rejection: {m5_confirm.reason}")
        return

    # Signal Payload
    signal_payload = {
        "signal_id": signal_id,
        "state": "ACTIONABLE",
        "symbol": symbol,
        "direction": candidate.direction.value,
        "strategy": candidate.strategy_name,
        "entry": risk_result.entry_price,
        "stop_loss": risk_result.stop_loss,
        "take_profit": risk_result.take_profit,
        "risk_reward": risk_result.risk_reward_ratio,
        "position_size": risk_result.position_size,
        "risk_amount_usd": risk_result.risk_amount_usd,
        "score": score_breakdown.total_score,
        "score_band": score_breakdown.score_band,
        "m5_confirmation": True,
        "news_status": news_check.status.value
    }

    # Step 10: Execution & Dispatch
    order_res = execution_provider.place_order(signal_payload)
    telegram_dispatcher.dispatch_actionable_signal(signal_payload)

    print(f"[{symbol}] 🚀 ACTIONABLE SIGNAL EXECUTED -> Order ID: {order_res.order_id}")

def trading_engine_loop():
    print("🚀 Background Quantitative Trading Engine Thread Started...")
    while True:
        if settings.KILL_SWITCH or not settings.MASTER_ENABLE:
            print("🛑 Engine Paused by Safety Gate (Kill Switch Active or Master Disabled)")
        else:
            print("🔍 Engine Scanning Markets...")
            for symbol in SYMBOLS_TO_SCAN:
                try:
                    process_market_scan(symbol)
                except Exception as e:
                    print(f"[Engine Error] Scan Exception for {symbol}: {e}")
        time.sleep(60)

# Start background strategy thread
threading.Thread(target=trading_engine_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)
