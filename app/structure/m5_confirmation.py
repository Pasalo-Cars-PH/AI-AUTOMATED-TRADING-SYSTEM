from pydantic import BaseModel
from typing import List
from app.data.normalizer import MarketCandle

class M5ConfirmationResult(BaseModel):
    confirmed: bool
    reason: str

class M5ConfirmationEngine:
    @staticmethod
    def validate_m5_close(
        m5_candles: List[MarketCandle],
        setup_zone_high: float,
        setup_zone_low: float,
        direction: str
    ) -> M5ConfirmationResult:
        if not m5_candles or len(m5_candles) < 2:
            return M5ConfirmationResult(confirmed=False, reason="Insufficient M5 candle data.")

        latest_closed_m5 = m5_candles[-1]

        if direction == "LONG":
            if latest_closed_m5.close > setup_zone_high:
                return M5ConfirmationResult(
                    confirmed=True,
                    reason=f"M5 closed ({latest_closed_m5.close:.4f}) above setup zone high ({setup_zone_high:.4f})."
                )
            return M5ConfirmationResult(
                confirmed=False,
                reason=f"M5 close ({latest_closed_m5.close:.4f}) failed to break setup zone boundary ({setup_zone_high:.4f})."
            )

        elif direction == "SHORT":
            if latest_closed_m5.close < setup_zone_low:
                return M5ConfirmationResult(
                    confirmed=True,
                    reason=f"M5 closed ({latest_closed_m5.close:.4f}) below setup zone low ({setup_zone_low:.4f})."
                )
            return M5ConfirmationResult(
                confirmed=False,
                reason=f"M5 close ({latest_closed_m5.close:.4f}) failed to break setup zone boundary ({setup_zone_low:.4f})."
            )

        return M5ConfirmationResult(confirmed=False, reason="Invalid direction.")
