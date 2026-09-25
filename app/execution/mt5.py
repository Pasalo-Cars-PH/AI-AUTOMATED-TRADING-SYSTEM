from typing import List
from app.execution.base import ExecutionProvider
from app.execution.schemas import OrderRequest, OrderResult, AccountState, PositionState, ExecutionState
from app.config import settings

class MT5ExecutionProvider(ExecutionProvider):
    def __init__(self):
        self.connected = False

    def connect(self) -> bool:
        self.connected = True
        return True

    def disconnect(self) -> None: self.connected = False
    def health_check(self) -> bool: return self.connected

    def get_account(self) -> AccountState:
        return AccountState(equity=10000.0, balance=10000.0, free_margin=10000.0, open_positions_count=0)

    def get_open_positions(self) -> List[PositionState]: return []

    def validate_order(self, request: OrderRequest) -> bool:
        return settings.MASTER_ENABLE and not settings.KILL_SWITCH

    def calculate_position_size(self, symbol: str, entry: float, sl: float, risk_pct: float) -> float:
        return 0.01

    def place_market_order(self, request: OrderRequest) -> OrderResult:
        if not self.validate_order(request):
            return OrderResult(
                success=False, execution_id="", symbol=request.symbol, direction=request.direction,
                requested_price=request.entry_price, executed_price=0.0, volume=request.volume,
                state=ExecutionState.REJECTED, message="Safety gate blocked live MT5 execution"
            )
        return OrderResult(
            success=True, execution_id="MT5_EXEC_1", order_id="MT5_1001", symbol=request.symbol,
            direction=request.direction, requested_price=request.entry_price,
            executed_price=request.entry_price, volume=request.volume, state=ExecutionState.FILLED,
            message="Submitted to MT5 Bridge"
        )

    def close_position(self, position_id: str) -> OrderResult:
        return OrderResult(
            success=True, execution_id="MT5_CLOSE_1", order_id=position_id, symbol="", direction="",
            requested_price=0, executed_price=0, volume=0, state=ExecutionState.CLOSED, message="Closed on MT5"
        )
