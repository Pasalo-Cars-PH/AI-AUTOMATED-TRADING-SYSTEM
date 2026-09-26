from fastapi import APIRouter, status, HTTPException
from app.market.service import market_service
from app.strategy.evaluator import strategy_evaluator

router = APIRouter(prefix="/market", tags=["Market Data"])

@router.get("/status", status_code=status.HTTP_200_OK)
async def get_market_status():
    return {
        "status": "HEALTHY",
        "health": market_service.get_health()
    }

@router.get("/health", status_code=status.HTTP_200_OK)
async def get_market_health():
    """Observability endpoint for market data health status per symbol."""
    return {
        "status": "HEALTHY",
        "symbols": market_service.get_health()
    }

@router.get("/quote/{symbol}", status_code=status.HTTP_200_OK)
async def get_quote(symbol: str):
    q = await market_service.get_quote(symbol.upper())
    if not q:
        raise HTTPException(status_code=404, detail=f"Quote unavailable for {symbol}")
    return q

@router.get("/candles/{symbol}/{timeframe}", status_code=status.HTTP_200_OK)
async def get_candles(symbol: str, timeframe: str):
    # Sinisigurong updated ang cache bago ibalik ang candles
    await market_service.update_symbol_data(symbol.upper(), timeframe.upper())
    candles = market_service.get_candles(symbol.upper(), timeframe.upper())
    
    return {
        "symbol": symbol.upper(),
        "timeframe": timeframe.upper(),
        "count": len(candles),
        "candles": candles
    }

@router.get("/analyze/{symbol}/{timeframe}", status_code=status.HTTP_200_OK)
async def analyze_symbol(symbol: str, timeframe: str = "M5"):
    await market_service.update_symbol_data(symbol.upper(), timeframe.upper())
    candles = market_service.get_candles(symbol.upper(), timeframe.upper())
    
    if not candles:
        raise HTTPException(status_code=404, detail=f"No candle data available for {symbol}")
        
    analysis = strategy_evaluator.evaluate_m5_setup(symbol.upper(), candles)
    return analysis
