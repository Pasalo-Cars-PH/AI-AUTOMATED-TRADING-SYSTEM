import uuid
from typing import Dict, List
from app.execution.base import ExecutionProvider, AccountState, OrderResult

class PaperExecutionProvider(ExecutionProvider):
    def __init__(self, initial_balance: float = 10000.0):
        self.balance = initial_balance
        self.equity = initial_balance
        self.positions: List[Dict] = []

    def get_account_state(self) -> AccountState:
        return AccountState(
            equity=self.equity,
            balance=self.balance,
            free_margin=self.balance,
            open_positions_count=len(self.positions)
        )

    def validate_order(self, signal: Dict) -> bool:
        # Check required fields
        required = ["symbol", "direction", "entry", "stop_loss", "take_profit", "position_size"]
        return all(k in signal and signal[k] is not None for k in required)

    def place_order(self, signal: Dict) -> OrderResult:
        if not self.validate_order(signal):
            return OrderResult(
                success=False, order_id="", symbol=signal.get("symbol", ""),
                direction=signal.get("direction", ""), fill_price=0.0, volume=0.0,
                message="Order validation failed: Missing required fields"
            )

        order_id = f"PAPER_{uuid.uuid4().hex[:8].upper()}"
        pos = {
            "order_id": order_id,
            "symbol": signal["symbol"],
            "direction": signal["direction"],
            "entry_price": signal["entry"],
            "stop_loss": signal["stop_loss"],
            "take_profit": signal["take_profit"],
            "volume": signal["position_size"],
            "status": "OPEN"
        }
        self.positions.append(pos)

        return OrderResult(
            success=True,
            order_id=order_id,
            symbol=signal["symbol"],
            direction=signal["direction"],
            fill_price=signal["entry"],
            volume=signal["position_size"],
            message="Paper Order Executed Successfully"
        )

    def close_order(self, order_id: str) -> bool:
        for p in self.positions:
            if p["order_id"] == order_id:
                p["status"] = "CLOSED"
                self.positions.remove(p)
                return True
        return False

    def get_open_positions(self) -> List[Dict]:
        return [p for p in self.positions if p["status"] == "OPEN"]
