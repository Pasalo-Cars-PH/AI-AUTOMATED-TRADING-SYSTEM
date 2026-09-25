import requests
from app.config import settings

class MT5BridgeClient:
    def __init__(self):
        self.bridge_url = getattr(settings, "MT5_BRIDGE_URL", "http://localhost:8000")
        self.api_key = getattr(settings, "MT5_BRIDGE_API_KEY", "")

    def check_health(self) -> bool:
        try:
            res = requests.get(f"{self.bridge_url}/health", headers={"X-API-KEY": self.api_key}, timeout=3)
            return res.status_code == 200
        except Exception:
            return False
