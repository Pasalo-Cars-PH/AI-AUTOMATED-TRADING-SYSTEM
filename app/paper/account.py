import os
import datetime
from typing import List, Dict, Any, Optional
from app.paper.models import PaperPosition, PositionState, NoTradeLog, SignalState

class PaperAccountManager:
    def __init__(self):
        self.initial_balance = float(os.getenv("PAPER_INITIAL_BALANCE", 100000.0))
        self.balance = self.initial_balance
        self.equity = self.initial_balance
        self.risk_per_trade = float(os.getenv("PAPER_RISK_PER_TRADE", 0.01))
        self.commission_per_lot = float(os.getenv("PAPER_COMMISSION", 7.0))
        self.spread_pips = float(os.getenv("PAPER_SPREAD", 0.0002))
        self.slippage_pips = float(os.getenv("PAPER_SLIPPAGE", 0.0001))
        
        # Risk Protections
        self.max_daily_loss_pct = float(os.getenv("MAX_DAILY_LOSS_PCT", 0.05))
        self.max_consecutive_losses = int(os.getenv("MAX_CONSECUTIVE_LOSSES", 3))
        self.consecutive_losses = 0
        
        # In-Memory Databases
        self.open_positions: Dict[str, PaperPosition] = {}
        self.closed_positions: List[PaperPosition] = []
        self.no_trade_logs: List[NoTradeLog] = []
        self.processed_signals: Dict[str, float] = {}  # Hash -> Timestamp
        
        # Daily Stats Tracking
        self.daily_start_balance = self.initial_balance

    def check_risk_limits() -> tuple[bool, Optional[str]]:
        daily_pnl_pct = (self.equity - self.daily_start_balance) / self.daily_start_balance
        if daily_pnl_pct <= -self.max_daily_loss_pct:
            return False, "DAILY_LOSS_LIMIT_REACHED"
        
        if self.consecutive_losses >= self.max_consecutive_losses:
            return False, "MAX_CONSECUTIVE_LOSSES_REACHED"
            
        return True, None

    def execute_paper_order(
        self, 
        signal_id: str,
        symbol: str, 
        direction: str, 
        strategy: str, 
        score: float, 
        entry_price: float, 
        stop_loss: float, 
        take_profit: float,
        timeframe: str = "M15"
    ) -> Optional[PaperPosition]:
        
        # Hard Safety Guard
        if os.getenv("TRADING_MODE", "PAPER") != "PAPER":
            return None

        # Risk Check
        allowed, reason = self.check_risk_limits()
        if not allowed:
            self.log_no_trade(signal_id, symbol, direction, strategy, score, reason or "RISK_LIMIT", timeframe)
            return None

        # Spread & Slippage Adjustments
        slippage = self.slippage_pips
        spread = self.spread_pips
        
        if direction == "BUY":
            simulated_entry = entry_price + spread + slippage
        else:
            simulated_entry = entry_price - spread - slippage

        # Calculate Lot Size based on Risk
        sl_distance = abs(simulated_entry - stop_loss)
        if sl_distance == 0:
            return None

        risk_amount = self.equity * self.risk_per_trade
        volume = round(risk_amount / (sl_distance * 100000), 2)
        if volume < 0.01:
            volume = 0.01

        commission = volume * self.commission_per_lot

        pos = PaperPosition(
            signal_id=signal_id,
            symbol=symbol,
            direction=direction,
            strategy=strategy,
            score=score,
            signal_price=entry_price,
            requested_entry=entry_price,
            simulated_entry=simulated_entry,
            current_price=simulated_entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            volume=volume,
            risk_percentage=self.risk_per_trade * 100,
            spread=spread,
            slippage=slippage,
            commission=commission,
            timeframe=timeframe
        )

        self.open_positions[pos.position_id] = pos
        return pos

    def update_positions(self, market_prices: Dict[str, float]):
        total_unrealized = 0.0

        for pos_id, pos in list(self.open_positions.items()):
            if pos.symbol not in market_prices:
                continue

            price = market_prices[pos.symbol]
            pos.current_price = price
            pos.last_update_time = datetime.datetime.utcnow().isoformat() + "Z"

            # Calculate Excursion (MAE & MFE)
            if pos.direction == "BUY":
                pnl = (price - pos.simulated_entry) * pos.volume * 100000 - pos.commission
                favorable = price - pos.simulated_entry
                adverse = pos.simulated_entry - price
            else:
                pnl = (pos.simulated_entry - price) * pos.volume * 100000 - pos.commission
                favorable = pos.simulated_entry - price
                adverse = price - pos.simulated_entry

            pos.unrealized_pnl = pnl
            total_unrealized += pnl

            if favorable > pos.mfe: pos.mfe = favorable
            if adverse > pos.mae: pos.mae = adverse

            # SL/TP Checking
            hit_sl = (price <= pos.stop_loss) if pos.direction == "BUY" else (price >= pos.stop_loss)
            hit_tp = (price >= pos.take_profit) if pos.direction == "BUY" else (price <= pos.take_profit)

            if hit_sl or hit_tp:
                self.close_position(pos_id, price, "TAKE_PROFIT" if hit_tp else "STOP_LOSS")

        self.equity = self.balance + total_unrealized

    def close_position(self, position_id: str, exit_price: float, reason: str):
        if position_id not in self.open_positions:
            return

        pos = self.open_positions.pop(position_id)
        pos.exit_price = exit_price
        pos.exit_reason = reason
        pos.exit_time = datetime.datetime.utcnow().isoformat() + "Z"
        pos.state = PositionState.CLOSED

        if pos.direction == "BUY":
            gross_pnl = (exit_price - pos.simulated_entry) * pos.volume * 100000
        else:
            gross_pnl = (pos.simulated_entry - exit_price) * pos.volume * 100000

        pos.realized_pnl = gross_pnl - pos.commission
        
        # Calculate R Multiple
        sl_distance = abs(pos.simulated_entry - pos.stop_loss)
        if sl_distance > 0:
            pos.r_multiple = round(pos.realized_pnl / (sl_distance * pos.volume * 100000), 2)

        self.balance += pos.realized_pnl
        self.equity = self.balance
        
        if pos.realized_pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        self.closed_positions.append(pos)

    def log_no_trade(self, signal_id: str, symbol: str, direction: str, strategy: str, score: float, reason: str, timeframe: str):
        log = NoTradeLog(
            signal_id=signal_id,
            symbol=symbol,
            direction=direction,
            strategy=strategy,
            score=score,
            rejection_reason=reason,
            timeframe=timeframe
        )
        self.no_trade_logs.append(log)

paper_account = PaperAccountManager()
