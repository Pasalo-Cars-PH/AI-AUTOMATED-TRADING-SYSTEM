from fastapi import APIRouter, status, HTTPException
from app.market.service import market_service

router = APIRouter(prefix="/market", tags=["Market Data"])

@router.get("/status", status_code=status.HTTP_200_OK)
async def get_market_status():
    return market_service.get_status()

@router.get("/health", status_code=status.HTTP_200_OK)
async def get_market_health():
    return {
        "status": "HEALTHY",
        "binance": market_service.binance.status.value,
        "twelvedata": market_service.twelvedata.status.value
    }

@router.get("/quote/{symbol}", status_code=status.HTTP_200_OK)
async def get_quote(symbol: str):
    q = await market_service.get_quote_async(symbol.upper())
    if not q:
        raise HTTPException(status_code=404, detail=f"Quote unavailable for {symbol}")
    return q

@router.get("/candles/{symbol}/{timeframe}", status_code=status.HTTP_200_OK)
async def get_candles(symbol: str, timeframe: str):
    candles = await market_service.get_candles_async(symbol.upper(), timeframe.upper())
    return {
        "symbol": symbol.upper(),
        "timeframe": timeframe.upper(),
        "count": len(candles),
        "fresh": market_service.is_data_fresh(symbol.upper(), timeframe.upper()),
        "candles": candles
    }
