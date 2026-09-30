from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_root_get_and_head():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "PAPER"
    assert data["master_enable"] is False
    assert data["kill_switch"] is True

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["kill_switch"] is True

def test_signal_execution_lock():
    response = client.get("/signal")
    assert response.status_code == 200
    data = response.json()
    assert data["reason"] == "STRICT_EXECUTION_LOCK_ACTIVE"
    assert data["mode"] == "PAPER"
