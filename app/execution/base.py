from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from pydantic import BaseModel

class AccountState(BaseModel):
    equity: float
    balance: float
    free_margin: float
    open_positions_count: int

class OrderResult(BaseModel):
    success: bool
    order_id: str
    symbol: str
    direction: str
    fill_price: float
    volume: float
    message: str

class ExecutionProvider(ABC):
    @abstractmethod
    def get_account_state(self) -> AccountState:
        pass

    @abstractmethod
    def validate_order(self, signal: Dict) -> bool:
        pass

    @abstractmethod
    def place_order(self, signal: Dict) -> OrderResult:
        pass

    @abstractmethod
    def close_order(self, order_id: str) -> bool:
        pass

    @abstractmethod
    def get_open_positions(() -> List[Dict]:
        pass
