# app/strategy/evaluator.py

def _get_candle_val(candle, field_name: str, default=0.0):
    if hasattr(candle, field_name):
        return getattr(candle, field_name)
    elif isinstance(candle, dict):
        return candle.get(field_name, default)
    return default

class StrategyEvaluator:
    def evaluate_m5_setup(self, symbol: str, candles: list) -> dict:
        if not candles:
            return {"action": "HOLD", "score": 0, "reasons": ["No candles provided"]}

        latest = candles[-1]
        
        # Ligtas na pagkuha ng close price para sa object o dict
        close_price = _get_candle_val(latest, "close")
        open_price = _get_candle_val(latest, "open")
        high_price = _get_candle_val(latest, "high")
        low_price = _get_candle_val(latest, "low")

        # Iagay ang natitirang evaluation logic ng strategy mo rito...
        # halimbawa:
        score = 0
        reasons = []

        # Simple example validation / confluence check
        if close_price > open_price:
            score += 50
            reasons.append("Bullish M5 candle close")

        action = "HOLD"
        if score >= 70:
            action = "BUY"

        # Tiyaking kasama ang 'latest_price' sa ibinabalik na dictionary
        return {
            "symbol": symbol,
            "action": action,
            "score": score,
            "latest_price": close_price,
            "trade_parameters": {
                "stop_loss": low_price,
                "take_profit": close_price + (close_price - low_price) * 2
            },
            "reasons": reasons
        }

strategy_evaluator = StrategyEvaluator()
