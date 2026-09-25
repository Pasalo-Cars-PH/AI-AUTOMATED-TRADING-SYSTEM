from typing import List
from app.execution.schemas import PositionState

class PositionMonitor:
    @staticmethod
    def inspect_positions(positions: List[PositionState]) -> dict:
        total_pnl = sum(p.unrealized_pnl for p in positions)
        return {
            "active_positions": len(positions),
            "total_unrealized_pnl": total_pnl,
            "status": "HEALTHY"
        }
