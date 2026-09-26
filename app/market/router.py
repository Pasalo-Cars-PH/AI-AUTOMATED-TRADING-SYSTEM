from fastapi import APIRouter, HTTPException, status
from app.market.service import market_service

router = APIRouter(prefix="/market", tags=["Market Data"])

@router.get("/health", status_code=status.HTTP_200_OK)
async def get_market_health():
    return market_service.get_health()

@router.get("/status", status_code=status.HTTP_200_OK)
async def get_market_status():
    try:
        return market_service.get_status()
    except Exception as e:
        return {
            "status": "DEGRADED",
            "error": str(e),
            "symbols": {}
        }

@router.get("/quote/{symbol}", status_code=status.HTTP_200_OK)
async def get_quote(symbol: str):
    quote = await market_service.get_quote(symbol)
    if not quote:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Quote unavailable for {symbol}"
        )
    return quote

@router.get("/candles/{symbol}/{timeframe}", status_code=status.HTTP_200_OK)
async def get_candles(symbol: str, timeframe: str, count: int = 100):
    candles = await market_service.get_candles(symbol, timeframe, count)
    return {
        "symbol": symbol.upper(),
        "timeframe": timeframe.upper(),
        "count": len(candles),
        "fresh": len(candles) > 0,
        "candles": candles
    }
