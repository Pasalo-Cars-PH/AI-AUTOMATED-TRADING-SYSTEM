from fastapi import APIRouter, status, HTTPException
import pandas as pd
import logging
from app.market.service import market_service
from app.strategy.evaluator import strategy_evaluator

logger = logging.getLogger("trading_bot")
router = APIRouter(prefix="/market", tags=["Market Data"])


@router.get("/status", status_code=status.HTTP_200_OK)
async def get_market_status():
    health = market_service.get_health()
    healthy = any(
        frame.get("status") == "HEALTHY"
        for frames in health.values()
        for frame in frames.values()
    )
    return {"status": "HEALTHY" if healthy else "DEGRADED", "health": health}


@router.get("/health", status_code=status.HTTP_200_OK)
async def get_market_health():
    """Read-only market-data health, including stale/invalid candle rejection."""
    health = market_service.get_health()
    healthy = any(
        frame.get("status") == "HEALTHY"
        for frames in health.values()
        for frame in frames.values()
    )
    return {"status": "HEALTHY" if healthy else "DEGRADED", "symbols": health}


@router.get("/quote/{symbol}", status_code=status.HTTP_200_OK)
async def get_quote(symbol: str):
    try:
        q = await market_service.get_quote(symbol.upper())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not q:
        raise HTTPException(status_code=404, detail=f"Fresh closed-candle quote unavailable for {symbol}")
    return q


@router.get("/candles/{symbol}/{timeframe}", status_code=status.HTTP_200_OK)
async def get_candles(symbol: str, timeframe: str):
    try:
        candles = await market_service.get_candles(symbol.upper(), timeframe.upper())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not candles:
        raise HTTPException(status_code=503, detail=f"No fresh valid closed candles available for {symbol}")
    return {
        "symbol": symbol.upper(),
        "timeframe": timeframe.upper(),
        "count": len(candles),
        "data_status": "LIVE_CLOSED_CANDLES",
        "candles": candles,
    }


@router.get("/analyze/{symbol}/{timeframe}", status_code=status.HTTP_200_OK)
async def analyze_symbol(symbol: str, timeframe: str = "M5"):
    """Read-only M5 analysis using validated closed M5 and H1 candles."""
    if timeframe.upper() != "M5":
        raise HTTPException(status_code=400, detail="ANALYZER_TIMEFRAME_REQUIRES_M5")
    try:
        m5 = await market_service.get_candles(symbol.upper(), "M5", limit=100)
        h1 = await market_service.get_candles(symbol.upper(), "H1", limit=100)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if len(m5) < 50 or len(h1) < 50:
        raise HTTPException(
            status_code=503,
            detail={"error": "INSUFFICIENT_VALID_CLOSED_CANDLES", "symbol": symbol.upper(),
                    "m5_count": len(m5), "h1_count": len(h1), "required_per_timeframe": 50},
        )
    def frame(candles):
        return pd.DataFrame([{
            "timestamp": int(x.timestamp), "open": float(x.open), "high": float(x.high),
            "low": float(x.low), "close": float(x.close), "volume": float(x.volume)
        } for x in candles]).sort_values("timestamp").reset_index(drop=True)
    try:
        result = strategy_evaluator.evaluate(frame(m5), frame(h1), symbol.upper())
    except Exception as exc:
        logger.exception("MARKET_ANALYSIS_FAILED | symbol=%s", symbol.upper())
        raise HTTPException(status_code=503, detail="INDICATOR_ANALYSIS_UNAVAILABLE") from exc
    if not isinstance(result, dict) or result.get("signal") not in {"BUY", "SELL", "NEUTRAL"}:
        raise HTTPException(status_code=503, detail="INVALID_ANALYZER_RESULT")
    result["data_status"] = "LIVE_CLOSED_CANDLES"
    result["m5_closed_candles"] = len(m5)
    result["h1_closed_candles"] = len(h1)
    result["execution"] = "DISABLED_PAPER_ONLY"
    return result
