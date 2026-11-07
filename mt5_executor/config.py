from dataclasses import dataclass
import os
from dotenv import load_dotenv
load_dotenv()
ALLOWED_SYMBOLS=("GBPJPY","USDJPY")
TIMEFRAMES=("H4","H1","M15","M5")
@dataclass(frozen=True)
class Settings:
    mode:str=os.getenv("MT5_MODE","DEMO").upper()
    allow_orders:bool=os.getenv("MT5_ALLOW_ORDERS","false").lower()=="true"
    risk_pct:float=float(os.getenv("MT5_RISK_PCT","1.0"))
    max_forex_lot:float=float(os.getenv("MT5_MAX_FOREX_LOT","0.02"))
    min_score:int=int(os.getenv("MT5_MIN_SCORE","80"))
    magic:int=int(os.getenv("MT5_MAGIC","6110701"))
    deviation_points:int=int(os.getenv("MT5_DEVIATION_POINTS","20"))
    state_file:str=os.getenv("MT5_STATE_FILE","mt5_executor_state.json")
    poll_seconds:int=int(os.getenv("MT5_POLL_SECONDS","10"))
    def validate(self):
        if self.mode!="DEMO": raise RuntimeError("MT5_MODE must be DEMO. Live mode is not implemented.")
        if not 0<self.risk_pct<=1.0: raise ValueError("MT5_RISK_PCT must be >0 and <=1.0.")
        if not 0<self.max_forex_lot<=0.02: raise ValueError("MT5_MAX_FOREX_LOT must be >0 and <=0.02.")
        if self.min_score!=80: raise ValueError("Entry threshold is fixed at 80/100.")
        if self.magic<=0: raise ValueError("MT5_MAGIC must be positive.")
SETTINGS=Settings()
