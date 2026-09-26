import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_root_get_and_head():
    res_get = client.get("/")
    assert res_get.status_code == 200
    assert "online" in res_get.json()["status"]

def test_health_endpoint():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "healthy"

def test_telegram_webhook_handling():
    res = client.post("/telegram/webhook", json={"update_id": 12345})
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
