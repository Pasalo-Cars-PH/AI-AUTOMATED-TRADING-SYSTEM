from fastapi import APIRouter, status, HTTPException
from app.market.service import market_service
from app.strategy.evaluator import strategy_evaluator

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
    try:
        candles = await market_service.get_candles(symbol.upper(), timeframe.upper())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not candles:
        raise HTTPException(status_code=503, detail=f"No fresh valid closed candles available for {symbol}")
    return strategy_evaluator.evaluate_m5_setup(symbol.upper(), candles)
