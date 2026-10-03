import os
import pandas as pd
import numpy as np
import datetime
import json

from app.structure.multi_timeframe import analyze_h1_structure_v2, analyze_m15_setup_v2
from app.journal.intrabar_lifecycle import evaluate_intrabar_lifecycle

class PhaseCReplayRunner:
    def __init__(self, symbol: str, df_h1: pd.DataFrame, df_m15: pd.DataFrame, df_m5: pd.DataFrame, df_m1: pd.DataFrame):
        self.symbol = symbol
        self.df_h1 = df_h1
        self.df_m15 = df_m15
        self.df_m5 = df_m5
        self.df_m1 = df_m1
        
        self.open_trades = []
        self.closed_trades = []
        self.rejected_setups = []

    def execute_replay(self, min_score_threshold=70):
        print(f"🚀 Starting Historical Replay for {self.symbol}...")
        
        # Warmup window: Lookback requirement for H1/M15 structures
        start_idx = 50
        total_bars = len(self.df_m5)

        for current_idx in range(start_idx, total_bars):
            current_time = self.df_m5.iloc[current_idx]["datetime_utc"]

            # 1. Zero-Lookahead Slice (strictly past and current closed candles)
            h1_slice = self.df_h1[self.df_h1["datetime_utc"] <= current_time].to_dict("records")
            m15_slice = self.df_m15[self.df_m15["datetime_utc"] <= current_time].to_dict("records")
            m5_slice = self.df_m5[self.df_m5["datetime_utc"] <= current_time].to_dict("records")

            if not h1_slice or not m15_slice or not m5_slice:
                continue

            # 2. Structure Engine Evaluation
            h1_res = analyze_h1_structure_v2(h1_slice)
            m15_res = analyze_m15_setup_v2(m15_slice, h1_res["bias"])

            total_score = h1_res["score"] + m15_res["score"]

            # 3. M5 Closed Trigger Validation
            latest_m5_close = m5_slice[-1]["close"]
            direction = h1_res["bias"]

            # 4. Check Criteria Entry Requirements
            if total_score >= min_score_threshold and direction in ["BULLISH", "BEARISH"] and m15_res["valid_setup"]:
                # Limit to 1 active trade per instrument at a time to prevent overlapping samples
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
                        "open_time": current_time,
                        "close_time": None,
                        "mfe": 0.0,
                        "mae": 0.0,
                        "result_r": 0.0,
                        "exit_reason": None
                    }
                    self.open_trades.append(trade)
            else:
                if total_score > 0:
                    self.rejected_setups.append({
                        "timestamp": current_time,
                        "score": total_score,
                        "reason": "SCORE_BELOW_THRESHOLD" if total_score < min_score_threshold else "INVALID_M15_SETUP"
                    })

            # 5. Intrabar Lifecycle Monitoring using M1 OHLC Bar
            m1_bar = self.df_m1[self.df_m1["datetime_utc"] == current_time]
            if not m1_bar.empty and len(self.open_trades) > 0:
                candle_data = m1_bar.to_dict("records")[0]
                candle_data["symbol"] = self.symbol
                
                # Process active open trades
                evaluate_intrabar_lifecycle(self.open_trades, candle_data)

            # Move closed trades to historical journal
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
            return {"symbol": self.symbol, "total_trades": 0, "status": "NO_TRADES_ACCEPTED"}

        df = pd.DataFrame(self.closed_trades)
        wins = df[df["result_r"] > 0]
        losses = df[df["result_r"] < 0]
        
        win_rate = (len(wins) / len(df)) * 100
        expectancy = df["result_r"].mean()
        profit_factor = abs(wins["result_r"].sum() / losses["result_r"].sum()) if len(losses) > 0 else np.nan

        return {
            "symbol": self.symbol,
            "total_samples": len(df),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_percent": round(win_rate, 2),
            "expectancy_r": round(expectancy, 2),
            "net_r_profit": round(df["result_r"].sum(), 2),
            "profit_factor": round(profit_factor, 2) if not np.isnan(profit_factor) else "N/A",
            "avg_mfe_pips": round(df["mfe"].mean(), 2),
            "avg_mae_pips": round(df["mae"].mean(), 2),
            "ambiguous_bars": len(df[df["exit_reason"] == "AMBIGUOUS_BAR_SL_PRIORITY"]),
            "timeout_trades": len(df[df["exit_reason"] == "TIMEOUT_EXPIRED"])
        }
