import requests
from datetime import datetime
from typing import List
from app.data.providers.base import BaseDataProvider
from app.data.normalizer import MarketCandle, DataQualityState

class BinanceDataProvider(BaseDataProvider):
    BASE_URL = "https://api.binance.com/api/v3/klines"

    TIMEFRAME_MAP = {
        "M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m",
        "H1": "1h", "H4": "4h", "D1": "1d"
    }

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200) -> List[MarketCandle]:
        tf = self.TIMEFRAME_MAP.get(timeframe, "15m")
        # Map symbol format (e.g., BTCUSD -> BTCUSDT)
        formatted_symbol = symbol.replace("USD", "USDT") if "USDT" not in symbol else symbol
        
        params = {"symbol": formatted_symbol, "interval": tf, "limit": limit}
        try:
            res = requests.get(self.BASE_URL, params=params, timeout=10)
            if res.status_code != 200:
                return []
            
            data = res.json()
            candles = []
            for row in data:
                candles.append(MarketCandle(
                    symbol=symbol,
                    timestamp=datetime.fromtimestamp(row[0] / 1000.0),
                    timeframe=timeframe,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                    source="Binance",
                    quality_state=DataQualityState.CONFIRMED_DATA
                ))
            return candles
        except Exception as e:
            print(f"[BinanceDataProvider] Ingestion Error: {e}")
            return []
