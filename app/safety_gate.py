import datetime
from typing import Dict, Any, List
from app.config import settings, TradingStatus, ApplicationStatus

class SafetyGate:
    def evaluate(
        self, 
        market_data_status: str = "CONNECTED",
        database_status: str = "CONNECTED",
        telegram_status: str = "CONFIGURED",
        news_status: str = "NOT_VERIFIED"
    ) -> Dict[str, Any]:
        
        blocking_reasons: List[str] = []
        warnings: List[str] = []

        if not settings.MASTER_ENABLE:
            blocking_reasons.append("MASTER_ENABLE is disabled (false)")

        if settings.KILL_SWITCH:
            blocking_reasons.append("KILL_SWITCH is activated (true)")

        if market_data_status not in ["CONNECTED", "DEGRADED"]:
            blocking_reasons.append(f"Market Data unavailable: {market_data_status}")
        elif market_data_status == "DEGRADED":
            warnings.append("Market Data status is DEGRADED")

        if database_status != "CONNECTED":
            blocking_reasons.append(f"Database unavailable: {database_status}")

        if telegram_status == "MISCONFIGURED":
            warnings.append("Telegram notification token/chat_id missing or invalid")

        if news_status != "VERIFIED":
            warnings.append(f"News Verification state: {news_status}")

        overall_allowed = len(blocking_reasons) == 0

        if overall_allowed:
            if settings.TRADING_MODE == "PAPER":
                trading_status = TradingStatus.READY_PAPER
            elif settings.TRADING_MODE == "DEMO":
                trading_status = TradingStatus.READY_DEMO
            elif settings.TRADING_MODE == "LIVE":
                trading_status = TradingStatus.READY_LIVE
            else:
                trading_status = TradingStatus.BLOCKED
                blocking_reasons.append(f"Invalid TRADING_MODE: {settings.TRADING_MODE}")
                overall_allowed = False
        else:
            trading_status = TradingStatus.PAUSED if not settings.MASTER_ENABLE or settings.KILL_SWITCH else TradingStatus.BLOCKED

        return {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "overall_allowed": overall_allowed,
            "trading_status": trading_status.value,
            "application_status": ApplicationStatus.HEALTHY.value,
            "mode": settings.TRADING_MODE,
            "checks": {
                "MASTER_ENABLE": {
                    "status": "PASS" if settings.MASTER_ENABLE else "FAIL",
                    "value": settings.MASTER_ENABLE,
                    "reason": None if settings.MASTER_ENABLE else "MASTER_ENABLE=false"
                },
                "KILL_SWITCH": {
                    "status": "PASS" if not settings.KILL_SWITCH else "FAIL",
                    "value": settings.KILL_SWITCH,
                    "reason": None if not settings.KILL_SWITCH else "KILL_SWITCH=true"
                },
                "TRADING_MODE": {
                    "status": "PASS",
                    "value": settings.TRADING_MODE
                },
                "MARKET_DATA": {
                    "status": "PASS" if market_data_status == "CONNECTED" else "WARN",
                    "value": market_data_status
                },
                "DATABASE": {
                    "status": "PASS" if database_status == "CONNECTED" else "FAIL",
                    "value": database_status
                },
                "TELEGRAM": {
                    "status": "PASS" if telegram_status == "CONFIGURED" else "WARN",
                    "value": telegram_status
                },
                "NEWS": {
                    "status": "PASS" if news_status == "VERIFIED" else "WARN",
                    "value": news_status
                },
                "EXECUTION": {
                    "status": "DISABLED",
                    "live_execution_allowed": False
                }
            },
            "blocking_reasons": blocking_reasons,
            "warnings": warnings
        }

safety_gate = SafetyGate()
