from datetime import datetime
from pydantic import BaseModel

class IndicatorResult(BaseModel):
    indicator_name: str
    value: float
    timestamp: datetime
    timeframe: str
    asset: str
    data_source: str
    calculated: bool = True
