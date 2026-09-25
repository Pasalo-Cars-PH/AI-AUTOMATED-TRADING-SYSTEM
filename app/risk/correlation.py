from typing import List, Dict

class CorrelationEngine:
    BUCKETS = {
        "USD-SHORT": ["EURUSD=X", "GBPUSD=X", "AUDUSD=X", "NZDUSD=X"],
        "USD-LONG": ["USDJPY=X", "USDCAD=X", "USDCHF=X"],
        "CRYPTO": ["BTC-USD", "ETH-USD", "SOL-USD"],
        "METALS": ["XAUUSD=X", "XAGUSD=X"]
    }

    @staticmethod
    def get_symbol_bucket(symbol: str, direction: str) -> str:
        symbol = symbol.upper()
        if symbol in CorrelationEngine.BUCKETS["CRYPTO"]:
            return "CRYPTO"
        if symbol in CorrelationEngine.BUCKETS["METALS"]:
            return "METALS"
        
        if direction == "LONG":
            if symbol in CorrelationEngine.BUCKETS["USD-SHORT"]:
                return "USD-SHORT"
            if symbol in CorrelationEngine.BUCKETS["USD-LONG"]:
                return "USD-LONG"
        elif direction == "SHORT":
            if symbol in CorrelationEngine.BUCKETS["USD-SHORT"]:
                return "USD-LONG"
            if symbol in CorrelationEngine.BUCKETS["USD-LONG"]:
                return "USD-SHORT"
        
        return "UNGROUPED"

    @staticmethod
    def validate_correlation(
        new_symbol: str, 
        new_direction: str, 
        active_positions: List[Dict], 
        max_bucket_risk: float = 0.015
    ) -> bool:
        new_bucket = CorrelationEngine.get_symbol_bucket(new_symbol, new_direction)
        if new_bucket == "UNGROUPED":
            return True

        current_bucket_risk = 0.0
        for pos in active_positions:
            bucket = CorrelationEngine.get_symbol_bucket(pos["symbol"], pos["direction"])
            if bucket == new_bucket:
                current_bucket_risk += pos.get("risk_amount_pct", 0.005)

        return (current_bucket_risk + 0.005) <= max_bucket_risk
