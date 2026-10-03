import pandas as pd
import numpy as np
import datetime

# --- EMBEDDED STRUCTURE LOGIC (PREVENTS RENDER MODULE IMPORT ERRORS) ---

def find_swing_points(candles, lookback=3):
    if len(candles) < (lookback * 2 + 1):
        return [], []
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    swing_highs, swing_lows = [], []

    for i in range(lookback, len(candles) - lookback):
        window_highs = highs[i - lookback : i + lookback + 1]
        window_lows = lows[i - lookback : i + lookback + 1]
        if highs[i] == max(window_highs):
            swing_highs.append({"index": i, "price": highs[i], "datetime": candles[i]["datetime_utc"]})
        if lows[i] == min(window_lows):
            swing_lows.append({"index": i, "price": lows[i], "datetime": candles[i]["datetime_utc"]})

    return swing_highs, swing_lows

def analyze_h1_structure_v2(candles):
    if not candles or len(candles) < 20:
        return {"bias": "NEUTRAL", "bos": False, "score": 0}
    closed_candles = candles[1:]
    swing_highs, swing_lows = find_swing_points(closed_candles, lookback=3)
    if not swing_highs or not swing_lows:
        return {"bias": "NEUTRAL", "bos": False, "score": 0}

    latest_close = closed_candles[0]["close"]
    recent_sh = swing_highs[-1]["price"]
    recent_sl = swing_lows[-1]["price"]

    if latest_close > recent_sh:
        return {"bias": "BULLISH", "bos": True, "score": 25, "key_level": recent_sh}
    elif latest_close < recent_sl:
        return {"bias": "BEARISH", "bos": True, "score": 25, "key_level": recent_sl}

    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        if swing_highs[-1]["price"] > swing_highs[-2]["price"] and swing_lows[-1]["price"] > swing_lows[-2]["price"]:
            return {"bias": "BULLISH", "bos": False, "score": 15, "key_level": recent_sl}
        elif swing_highs[-1]["price"] < swing_highs[-2]["price"] and swing_lows[-1]["price"] < swing_lows[-2]["price"]:
            return {"bias": "BEARISH", "bos": False, "score": 15, "key_level": recent_sh}

    return {"bias": "NEUTRAL", "bos": False, "score": 0}

def analyze_m15_setup_v2(candles, h1_bias):
    if not candles or len(candles) < 10 or h1_bias == "NEUTRAL":
        return {"valid_setup": False, "direction": None, "score": 0}
    c = candles[1:]
    bullish_fvg, bearish_fvg = False, False
    
    for i in range(len(c) - 3):
        if h1_bias == "BULLISH" and c[i]["low"] > c[i+2]["high"]:
            bullish_fvg = True
            break
        elif h1_bias == "BEARISH" and c[i]["high"] < c[i+2]["low"]:
            bearish_fvg = True
            break

    bullish_ob = (c[1]["close"] < c[1]["open"]) and (c[0]["close"] > c[0]["open"]) and (c[0]["close"] > c[1]["high"]) and (h1_bias == "BULLISH")
    bearish_ob = (c[1]["close"] > c[1]["open"]) and (c[0]["close"] < c[0]["open"]) and (c[0]["close"] < c[1]["low"]) and (h1_bias == "BEARISH")

    score = 0
    if (bullish_fvg and h1_bias == "BULLISH") or (bearish_fvg and h1_bias == "BEARISH"):
        score += 12
    if (bullish_ob and h1_bias == "BULLISH") or (bearish_ob and h1_bias == "BEARISH"):
        score += 13

    valid = score > 0
    direction = h1_bias if valid else None
    return {"valid_setup": valid, "direction": direction, "score": score}

def evaluate_intrabar_lifecycle(open_trades: list, current_m1_candle: dict):
    symbol = current_m1_candle["symbol"]
    high_p = current_m1_candle["high"]
    low_p = current_m1_candle["low"]

    for trade in open_trades:
        if trade["status"] != "OPEN" or trade["symbol"] != symbol:
            continue

        entry = trade["entry_price"]
        sl = trade["sl_price"]
        tp = trade["tp_price"]
        direction = trade["direction"]

        if direction == "BUY":
            trade["mfe"] = max(trade["mfe"], high_p - entry)
            trade["mae"] = max(trade["mae"], entry - low_p)
        else:
            trade["mfe"] = max(trade["mfe"], entry - low_p)
            trade["mae"] = max(trade["mae"], low_p - entry)

        sl_hit = low_p <= sl if direction == "BUY" else high_p >= sl
        tp_hit = high_p >= tp if direction == "BUY" else low_p <= tp
        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if sl_hit and tp_hit:
            trade["status"] = "CLOSED"
            trade["exit_price"] = sl
            trade["exit_reason"] = "AMBIGUOUS_BAR_SL_PRIORITY"
            trade["result_r"] = -1.0
            trade["close_time"] = now_utc
            continue

        if sl_hit:
            trade["status"] = "CLOSED"
            trade["exit_price"] = sl
            trade["exit_reason"] = "STOP_LOSS_HIT"
            trade["result_r"] = -1.0
            trade["close_time"] = now_utc
        elif tp_hit:
            trade["status"] = "CLOSED"
            trade["exit_price"] = tp
            trade["exit_reason"] = "TAKE_PROFIT_HIT"
            trade["result_r"] = trade["rr_ratio"]
            trade["close_time"] = now_utc

# --- REPLAY RUNNER ENGINE ---

class PhaseCReplayRunner:
    def __init__(self, symbol: str, df_h1: pd.DataFrame, df_m15: pd.DataFrame, df_m5: pd.DataFrame, df_m1: pd.DataFrame):
        self.symbol = symbol
        self.df_h1 = df_h1
        self.df_m15 = df_m15
        self.df_m5 = df_m5
        self.df_m1 = df_m1
        self.open_trades = []
        self.closed_trades = []

    def execute_replay(self, min_score_threshold=70):
        start_idx = 50
        total_bars = len(self.df_m5)

        for current_idx in range(start_idx, total_bars):
            current_time = self.df_m5.iloc[current_idx]["datetime_utc"]

            h1_slice = self.df_h1[self.df_h1["datetime_utc"] <= current_time].to_dict("records")
            m15_slice = self.df_m15[self.df_m15["datetime_utc"] <= current_time].to_dict("records")
            m5_slice = self.df_m5[self.df_m5["datetime_utc"] <= current_time].to_dict("records")

            if not h1_slice or not m15_slice or not m5_slice:
                continue

            h1_res = analyze_h1_structure_v2(h1_slice)
            m15_res = analyze_m15_setup_v2(m15_slice, h1_res["bias"])
            total_score = h1_res["score"] + m15_res["score"]
            latest_m5_close = m5_slice[-1]["close"]
            direction = h1_res["bias"]

            if total_score >= min_score_threshold and direction in ["BULLISH", "BEARISH"] and m15_res["valid_setup"]:
                if len(self.open_trades) == 0:
                    pip_unit = 0.1 if self.symbol == "XAUUSD" else 0.0001
                    sl_dist = 15.0 * pip_unit if self.symbol == "XAUUSD" else 7.0 * pip_unit
                    tp_dist = 30.0 * pip_unit if self.symbol == "XAUUSD" else 14.0 * pip_unit

                    entry_p = latest_m5_close
                    sl_p = entry_p - sl_dist if direction == "BULLISH" else entry_p + sl_dist
                    tp_p = entry_p + tp_dist if direction == "BULLISH" else entry_p - tp_dist

                    trade = {
                        "trade_id": f"BT-{self.symbol}-{current_idx}",
                        "symbol": self.symbol,
                        "direction": "BUY" if direction == "BULLISH" else "SELL",
                        "entry_price": entry_p,
                        "sl_price": round(sl_p, 4),
                        "tp_price": round(tp_p, 4),
                        "rr_ratio": 2.0,
                        "score": total_score,
                        "status": "OPEN",
                        "open_time": str(current_time),
                        "close_time": None,
                        "mfe": 0.0,
                        "mae": 0.0,
                        "result_r": 0.0,
                        "exit_reason": None
                    }
                    self.open_trades.append(trade)

            m1_bar = self.df_m1[self.df_m1["datetime_utc"] == current_time]
            if not m1_bar.empty and len(self.open_trades) > 0:
                candle_data = m1_bar.to_dict("records")[0]
                candle_data["symbol"] = self.symbol
                evaluate_intrabar_lifecycle(self.open_trades, candle_data)

            active = []
            for t in self.open_trades:
                if t["status"] == "CLOSED":
                    self.closed_trades.append(t)
                else:
                    active.append(t)
            self.open_trades = active

        return self.compile_metrics()

    def compile_metrics(self):
        if not self.closed_trades:
            return {"symbol": self.symbol, "total_samples": 0, "status": "NO_TRADES_ACCEPTED"}

        df = pd.DataFrame(self.closed_trades)
        wins = df[df["result_r"] > 0]
        losses = df[df["result_r"] < 0]
        win_rate = (len(wins) / len(df)) * 100 if len(df) > 0 else 0
        expectancy = df["result_r"].mean()

        return {
            "symbol": self.symbol,
            "total_samples": len(df),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_percent": round(win_rate, 2),
            "expectancy_r": round(expectancy, 2),
            "net_r_profit": round(df["result_r"].sum(), 2),
            "avg_mfe_pips": round(df["mfe"].mean(), 2),
            "avg_mae_pips": round(df["mae"].mean(), 2),
            "ambiguous_bars": len(df[df["exit_reason"] == "AMBIGUOUS_BAR_SL_PRIORITY"])
        }
