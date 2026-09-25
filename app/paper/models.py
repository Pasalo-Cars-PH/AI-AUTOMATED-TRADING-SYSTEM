import uuid
import datetime
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field

class SignalState(str, Enum):
    CANDIDATE = "CANDIDATE"
    TRIGGER = "TRIGGER"
    SETUP = "SETUP"
    ACTIONABLE = "ACTIONABLE"
    PAPER_OPEN = "PAPER_OPEN"
    MANAGEMENT = "MANAGEMENT"
    CLOSED = "CLOSED"
    NO_TRADE = "NO_TRADE"

class PositionState(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"

class PaperPosition(BaseModel):
    position_id: str = Field(default_factory=lambda: f"PPOS_{uuid.uuid4().hex[:8].upper()}")
    signal_id: str
    symbol: str
    direction: str
    strategy: str
    score: float
    state: PositionState = PositionState.OPEN
    
    # Prices
    signal_price: float
    requested_entry: float
    simulated_entry: float
    stop_loss: float
    take_profit: float
    current_price: float
    exit_price: Optional[float] = None
    
    # Sizing & Costs
    volume: float
    risk_percentage: float
    spread: float
    slippage: float
    commission: float
    
    # Timing
    entry_time: str = Field(default_factory=lambda: datetime.datetime.utcnow().isoformat() + "Z")
    exit_time: Optional[str] = None
    last_update_time: str = Field(default_factory=lambda: datetime.datetime.utcnow().isoformat() + "Z")
    
    # Analytics
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    r_multiple: float = 0.0
    mae: float = 0.0  # Maximum Adverse Excursion
    mfe: float = 0.0  # Maximum Favorable Excursion
    exit_reason: Optional[str] = None
    
    # Context
    market_regime: str = "TRENDING"
    timeframe: str = "M15"
    data_source: str = "binance"

class NoTradeLog(BaseModel):
    log_id: str = Field(default_factory=lambda: f"NT_{uuid.uuid4().hex[:8].upper()}")
    signal_id: str
    symbol: str
    direction: str
    strategy: str
    score: float
    rejection_reason: str
    timeframe: str
    timestamp: str = Field(default_factory=lambda: datetime.datetime.utcnow().isoformat() + "Z")
