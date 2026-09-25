import os
from enum import Enum
from pydantic_settings import BaseSettings

class ApplicationStatus(str, Enum):
    STARTING = "STARTING"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    ERROR = "ERROR"

class TradingStatus(str, Enum):
    STARTING = "STARTING"
    PAUSED = "PAUSED"
    READY_PAPER = "READY_PAPER"
    READY_DEMO = "READY_DEMO"
    READY_LIVE = "READY_LIVE"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"

class Settings(BaseSettings):
    APP_NAME: str = "ai-trading-bot-v2"
    MASTER_ENABLE: bool = False
    KILL_SWITCH: bool = True
    TRADING_MODE: str = "PAPER"
    
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./trading_bot.db")
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    MT5_ENABLED: bool = False

    class Config:
        env_file = ".env"
        extra = "allow"

settings = Settings()
