from abc import ABC, abstractmethod
from typing import List, Optional
from app.execution.schemas import OrderRequest, OrderResult, AccountState, PositionState

class ExecutionProvider(ABC):
    @abstractmethod
    def connect(self) -> bool: pass

    @abstractmethod
    def disconnect(self) -> None: pass

    @abstractmethod
    def health_check(self) -> bool: pass

    @abstractmethod
    def get_account(self) -> AccountState: pass

    @abstractmethod
    def get_open_positions(self) -> List[PositionState]: pass

    @abstractmethod
    def validate_order(self, request: OrderRequest) -> bool: pass

    @abstractmethod
    def calculate_position_size(self, symbol: str, entry: float, sl: float, risk_pct: float) -> float: pass

    @abstractmethod
    def place_market_order(self, request: OrderRequest) -> OrderResult: pass

    @abstractmethod
    def close_position(self, position_id: str) -> OrderResult: pass
