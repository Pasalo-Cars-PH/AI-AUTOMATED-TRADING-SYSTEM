from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_root_get_and_head():
    res_get = client.get("/")
    assert res_get.status_code == 200
    assert res_get.json()["service"] == "ai-trading-bot-v2"
    
    res_head = client.head("/")
    assert res_head.status_code == 200

def test_health_endpoint():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["application_status"] == "HEALTHY"

def test_status_endpoint_no_secrets():
    res = client.get("/status")
    assert res.status_code == 200
    data = res.json()
    assert "engine" in data
    assert "safety_gate" in data
    raw_str = res.text
    assert "TELEGRAM_BOT_TOKEN" not in raw_str
    assert "DATABASE_URL" not in raw_str

def test_safety_gate_blocking():
    res = client.get("/safety")
    assert res.status_code == 200
    data = res.json()
    assert data["overall_allowed"] is False
    assert "MASTER_ENABLE is disabled (false)" in data["blocking_reasons"]
    assert "KILL_SWITCH is activated (true)" in data["blocking_reasons"]
