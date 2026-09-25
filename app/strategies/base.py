from enum import Enum
from typing import List, Optional
from pydantic import BaseModel

class TradeDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"

class CandidateSetup(BaseModel):
    strategy_name: str
    direction: TradeDirection
    confidence: float
    trigger_level: float
    setup_zone_high: float
    setup_zone_low: float
    invalidation_level: float
    reasoning: List[str]
    required_confirmation: str = "M5_CLOSED_CANDLE"
