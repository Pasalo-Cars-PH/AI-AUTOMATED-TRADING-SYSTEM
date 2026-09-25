from app.config import settings
from app.execution.schemas import OrderRequest
from app.state.duplicate_detector import DuplicateDetector

class PreTradeValidator:
    @staticmethod
    def pre_trade_check(request: OrderRequest, account_equity: float, current_spread: float) -> dict:
        checks = {
            "kill_switch": not settings.KILL_SWITCH,
            "master_enable": settings.MASTER_ENABLE,
            "has_sl_tp": request.stop_loss > 0 and request.take_profit > 0,
            "valid_volume": request.volume > 0,
            "spread_ok": current_spread <= getattr(settings, "MAX_SPREAD_PIPS", 3.0),
            "duplicate_check": not DuplicateDetector.is_duplicate(
                f"{request.signal_id}_{request.symbol}_{request.direction}"
            )
        }
        
        rejections = [k for k, v in checks.items() if not v]
        return {
            "approved": len(rejections) == 0,
            "checks": checks,
            "rejection_reasons": rejections
        }
