import uuid
from typing import List
from app.execution.base import ExecutionProvider
from app.execution.schemas import OrderRequest, OrderResult, AccountState, PositionState, ExecutionState
from app.config import settings

class PaperExecutionProvider(ExecutionProvider):
    def __init__(self, initial_balance: float = 10000.0):
        self.balance = initial_balance
        self.equity = initial_balance
        self.positions: List[PositionState] = []

    def connect(self) -> bool: return True
    def disconnect(self) -> None: pass
    def health_check(self) -> bool: return True

    def get_account(self) -> AccountState:
        return AccountState(
            equity=self.equity,
            balance=self.balance,
            free_margin=self.balance,
            open_positions_count=len(self.positions)
        )

    def get_open_positions(self) -> List[PositionState]: return self.positions

    def validate_order(self, request: OrderRequest) -> bool:
        return request.volume > 0 and request.stop_loss > 0

    def calculate_position_size(self, symbol: str, entry: float, sl: float, risk_pct: float) -> float:
        risk_amount = self.equity * (risk_pct / 100.0)
        sl_distance = abs(entry - sl)
        if sl_distance == 0: return 0.01
        return round(risk_amount / sl_distance / 100.0, 2)

    def place_market_order(self, request: OrderRequest) -> OrderResult:
        slippage = getattr(settings, "PAPER_SLIPPAGE", 0.0001)
        exec_price = request.entry_price + slippage if request.direction == "BUY" else request.entry_price - slippage
        pos_id = f"PAPER_POS_{uuid.uuid4().hex[:6].upper()}"

        pos = PositionState(
            position_id=pos_id,
            symbol=request.symbol,
            direction=request.direction,
            volume=request.volume,
            entry_price=exec_price,
            current_price=exec_price,
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
            unrealized_pnl=0.0
        )
        self.positions.append(pos)

        return OrderResult(
            success=True,
            execution_id=f"EXEC_{uuid.uuid4().hex[:6].upper()}",
            order_id=pos_id,
            symbol=request.symbol,
            direction=request.direction,
            requested_price=request.entry_price,
            executed_price=exec_price,
            volume=request.volume,
            slippage=slippage,
            state=ExecutionState.FILLED,
            message="Paper order filled successfully"
        )

    def close_position(self, position_id: str) -> OrderResult:
        for p in self.positions:
            if p.position_id == position_id:
                self.positions.remove(p)
                return OrderResult(
                    success=True, execution_id="CLOSE_1", order_id=position_id,
                    symbol=p.symbol, direction=p.direction, requested_price=p.current_price,
                    executed_price=p.current_price, volume=p.volume, slippage=0.0,
                    state=ExecutionState.CLOSED, message="Position closed"
                )
        return OrderResult(
            success=False, execution_id="", symbol="", direction="", requested_price=0,
            executed_price=0, volume=0, state=ExecutionState.FAILED, message="Position not found"
        )
