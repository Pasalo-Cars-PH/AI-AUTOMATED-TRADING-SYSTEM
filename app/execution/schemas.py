from pydantic import BaseModel
from typing import Optional, List
from enum import Enum

class ExecutionState(str, Enum):
    PENDING = "PENDING"
    VALIDATING = "VALIDATING"
    REJECTED = "REJECTED"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    CLOSED = "CLOSED"
    FAILED = "FAILED"

class OrderRequest(BaseModel):
    signal_id: str
    symbol: str
    direction: str  # BUY or SELL
    order_type: str = "MARKET"
    volume: float
    entry_price: float
    stop_loss: float
    take_profit: float
    deviation: int = 10
    magic_number: int = 1001
    comment: str = "QuantEngine_v2"

class OrderResult(BaseModel):
    success: bool
    execution_id: str
    order_id: Optional[str] = None
    symbol: str
    direction: str
    requested_price: float
    executed_price: float = 0.0
    volume: float
    slippage: float = 0.0
    state: ExecutionState
    message: str

class AccountState(BaseModel):
    equity: float
    balance: float
    free_margin: float
    open_positions_count: int

class PositionState(BaseModel):
    position_id: str
    symbol: str
    direction: str
    volume: float
    entry_price: float
    current_price: float
    stop_loss: float
    take_profit: float
    unrealized_pnl: float
