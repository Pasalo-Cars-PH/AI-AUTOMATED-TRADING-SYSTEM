import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Quant Engine"
    MASTER_ENABLE: bool = False
    KILL_SWITCH: bool = True
    TRADING_MODE: str = "PAPER"  # PAPER or LIVE
    
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    
    PAPER_SLIPPAGE: float = 0.0001
    PAPER_SPREAD: float = 0.0002
    MAX_SPREAD_PIPS: float = 3.0
    
    MT5_BRIDGE_URL: str = os.getenv("MT5_BRIDGE_URL", "http://localhost:8000")
    MT5_BRIDGE_API_KEY: str = os.getenv("MT5_BRIDGE_API_KEY", "")

    class Config:
        env_file = ".env"

settings = Settings()
