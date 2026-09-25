import os
from pydantic import BaseSettings

class Settings(BaseSettings):
    # System Status
    MASTER_ENABLE: bool = os.getenv("MASTER_ENABLE", "True").lower() == "true"
    KILL_SWITCH: bool = os.getenv("KILL_SWITCH", "False").lower() == "true"
    TRADING_MODE: str = os.getenv("TRADING_MODE", "PAPER") # PAPER or LIVE
    
    # Telegram Credentials
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    
    # Risk Parameters
    RISK_PER_TRADE: float = float(os.getenv("RISK_PER_TRADE", "0.005")) # 0.5% default
    MAX_DAILY_LOSS: float = float(os.getenv("MAX_DAILY_LOSS", "0.02"))   # 2.0% max daily loss
    MAX_OPEN_POSITIONS: int = int(os.getenv("MAX_OPEN_POSITIONS", "6"))
    MIN_CONFLUENCE_SCORE: int = 75
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./trading_engine.db")

settings = Settings()
