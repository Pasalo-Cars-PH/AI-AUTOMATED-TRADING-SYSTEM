from fastapi.testclient import TestClient
import app.main as main

client = TestClient(main.app)

def telegram_update(command, chat_id="test-chat"):
    return {"update_id": 9000 + sum(ord(ch) for ch in command), "message": {"chat": {"id": chat_id}, "text": command}}

def test_paper_command_center_status_commands(monkeypatch, tmp_path):
    # Give read-only report commands an isolated ledger path; CI does not have
    # Render persistent storage mounted at /mnt/data.
    ledger = tmp_path / "paper-ledger.json"
    monkeypatch.setattr(main, "TRADES_FILE_PERSIST", str(ledger))
    monkeypatch.setattr(main, "TRADES_FILE", str(ledger))
    sent = []
    monkeypatch.setattr(main, "send_telegram_msg", lambda msg, chat_id=None: sent.append((msg, chat_id)))
    for command in ["/paperstatus", "/positions", "/performance", "/risk", "/journal"]:
        response = client.post("/telegram/webhook", json=telegram_update(command, chat_id=""))
        assert response.status_code == 200
    assert len(sent) == 5

def test_pause_and_resume_are_paper_only(monkeypatch):
    sent = []
    monkeypatch.setattr(main, "send_telegram_msg", lambda msg, chat_id=None: sent.append(msg))
    main.PAPER_SCAN_PAUSED = False

    assert client.post("/telegram/webhook", json=telegram_update("/pause", chat_id="")).status_code == 200
    assert main.PAPER_SCAN_PAUSED is True

    assert client.post("/telegram/webhook", json=telegram_update("/resume-paper", chat_id="")).status_code == 200
    assert main.PAPER_SCAN_PAUSED is False

    assert all("DISABLED" in msg for msg in sent)


def test_trade_apis_report_503_when_ledger_is_unavailable(monkeypatch):
    def unavailable():
        raise RuntimeError("paper_ledger_persistent_mount_missing:/mnt/data")

    monkeypatch.setattr(main, "load_trades", unavailable)
    for endpoint in ["/api/trades", "/api/stats"]:
        response = client.get(endpoint)
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "unavailable"
        assert body["error"] == "PAPER_LEDGER_UNAVAILABLE"
        assert body["trading_mode"] == "PAPER"
        assert body["live_execution"] is False

def test_execution_commands_remain_blocked():
    source = open("app/telegram.py", encoding="utf-8").read()
    for command in ["/unlock", "/buy", "/sell", "/order", "/trade", "/execute"]:
        assert command in source
