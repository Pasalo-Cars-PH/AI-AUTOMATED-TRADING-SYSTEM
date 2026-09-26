import httpx
import logging
from typing import List, Dict, Any

logger = logging.getLogger("trading_bot")

class DataFetcher:
    async def get_m5_candles(self, symbol: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Fetches M5 candle data using public Yahoo Finance API without authentication fees.
        """
        # Map symbols to standard Yahoo Finance tickers
        symbol_map = {
            "BTCUSD": "BTC-USD",
            "ETHUSD": "ETH-USD",
            "SOLUSD": "SOL-USD",
            "EURUSD": "EURUSD=X",
            "XAUUSD": "GC=F",
            "XAUUSD=X": "GC=F",
            "EURUSD=X": "EURUSD=X"
        }
        
        ticker = symbol_map.get(symbol.upper(), symbol)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=5m&range=1d"
        headers = {"User-Agent": "Mozilla/5.0"}

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers, timeout=10.0)
                if resp.status_code != 200:
                    logger.error(f"FETCH_ERROR | Status: {resp.status_code} for {symbol}")
                    return []

                data = resp.json()
                result = data["chart"]["result"][0]
                timestamps = result["timestamp"]
                quote = result["indicators"]["quote"][0]

                candles = []
                for i in range(len(timestamps)):
                    if (quote["open"][i] is not None and 
                        quote["high"][i] is not None and 
                        quote["low"][i] is not None and 
                        quote["close"][i] is not None):
                        candles.append({
                            "time": timestamps[i],
                            "open": float(quote["open"][i]),
                            "high": float(quote["high"][i]),
                            "low": float(quote["low"][i]),
                            "close": float(quote["close"][i]),
                            "volume": float(quote["volume"][i] or 0)
                        })

                return candles[-limit:]

        except Exception as e:
            logger.error(f"FETCH_EXCEPTION | {symbol}: {e}")
            return []

data_fetcher = DataFetcher()
